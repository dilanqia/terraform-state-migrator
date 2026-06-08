"""State file validation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """A single validation issue found in a state file."""

    severity: Severity
    message: str
    path: str = ""
    suggestion: str = ""

    def __str__(self) -> str:
        prefix = self.severity.value.upper()
        parts = [f"[{prefix}] {self.message}"]
        if self.path:
            parts.append(f"  at: {self.path}")
        if self.suggestion:
            parts.append(f"  fix: {self.suggestion}")
        return "\n".join(parts)


@dataclass
class ValidationResult:
    """Result of validating a Terraform state file."""

    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    terraform_version: str | None = None
    serial: int | None = None
    lineage: str | None = None
    resource_count: int = 0
    output_count: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    def summary(self) -> str:
        lines = [
            f"State Validation: {'PASS' if self.is_valid else 'FAIL'}",
            f"  Terraform version: {self.terraform_version or 'unknown'}",
            f"  Serial: {self.serial}",
            f"  Lineage: {self.lineage or 'none'}",
            f"  Resources: {self.resource_count}",
            f"  Outputs: {self.output_count}",
            f"  Issues: {len(self.errors)} errors, {len(self.warnings)} warnings",
        ]
        if self.issues:
            lines.append("")
            for issue in self.issues:
                lines.append(str(issue))
        return "\n".join(lines)


class StateValidator:
    """Validates Terraform state files for correctness and best practices.

    Checks:
    - Valid JSON structure
    - Required fields (version, serial, lineage)
    - Terraform state version compatibility
    - Resource reference integrity
    - Duplicate resource detection
    - Sensitive output handling
    """

    SUPPORTED_VERSIONS = {3, 4}

    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict

    def validate_file(self, path: str | Path) -> ValidationResult:
        """Validate a state file from disk."""
        path = Path(path)
        if not path.exists():
            return ValidationResult(
                is_valid=False,
                issues=[ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"File not found: {path}",
                )],
            )

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                issues=[ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Could not read file: {e}",
                )],
            )

        return self.validate_string(content)

    def validate_string(self, content: str) -> ValidationResult:
        """Validate a state file from a JSON string."""
        issues: list[ValidationIssue] = []

        # Parse JSON
        try:
            state = json.loads(content)
        except json.JSONDecodeError as e:
            return ValidationResult(
                is_valid=False,
                issues=[ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Invalid JSON: {e}",
                )],
            )

        if not isinstance(state, dict):
            return ValidationResult(
                is_valid=False,
                issues=[ValidationIssue(
                    severity=Severity.ERROR,
                    message="State file must be a JSON object",
                )],
            )

        # Validate version
        issues.extend(self._check_version(state))

        # Validate serial
        issues.extend(self._check_serial(state))

        # Validate lineage
        issues.extend(self._check_lineage(state))

        # Validate resources
        issues.extend(self._check_resources(state))

        # Validate outputs
        issues.extend(self._check_outputs(state))

        # Validate terraform_version
        issues.extend(self._check_terraform_version(state))

        # Validate provider schemas
        issues.extend(self._check_providers(state))

        has_errors = any(i.severity == Severity.ERROR for i in issues)

        return ValidationResult(
            is_valid=not has_errors,
            issues=issues,
            terraform_version=state.get("terraform_version"),
            serial=state.get("serial"),
            lineage=state.get("lineage"),
            resource_count=len(state.get("resources", [])),
            output_count=len(state.get("outputs", {})),
        )

    def _check_version(self, state: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        version = state.get("version")

        if version is None:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="Missing 'version' field",
                path="$.version",
                suggestion="Terraform state must include a version field (3 or 4)",
            ))
        elif not isinstance(version, int):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"'version' must be an integer, got {type(version).__name__}",
                path="$.version",
            ))
        elif version not in self.SUPPORTED_VERSIONS:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"Unsupported state version: {version}",
                path="$.version",
                suggestion=f"Supported versions: {', '.join(map(str, sorted(self.SUPPORTED_VERSIONS)))}",
            ))

        return issues

    def _check_serial(self, state: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        serial = state.get("serial")

        if serial is None:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message="Missing 'serial' field",
                path="$.serial",
                suggestion="Serial helps track state file revisions",
            ))
        elif not isinstance(serial, int) or serial < 0:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message=f"'serial' must be a non-negative integer, got {serial!r}",
                path="$.serial",
            ))

        return issues

    def _check_lineage(self, state: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        lineage = state.get("lineage")

        if lineage is None:
            severity = Severity.WARNING if self.strict else Severity.INFO
            issues.append(ValidationIssue(
                severity=severity,
                message="Missing 'lineage' field",
                path="$.lineage",
                suggestion="Lineage prevents accidental state overwrites from different configurations",
            ))
        elif not isinstance(lineage, str) or len(lineage) == 0:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message="'lineage' should be a non-empty string",
                path="$.lineage",
            ))

        return issues

    def _check_resources(self, state: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resources = state.get("resources", [])

        if not isinstance(resources, list):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="'resources' must be an array",
                path="$.resources",
            ))
            return issues

        seen: dict[str, list[int]] = {}

        for i, resource in enumerate(resources):
            path = f"$.resources[{i}]"

            if not isinstance(resource, dict):
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Resource must be an object, got {type(resource).__name__}",
                    path=path,
                ))
                continue

            # Check required fields
            for field_name in ("mode", "type", "name", "provider"):
                if field_name not in resource:
                    issues.append(ValidationIssue(
                        severity=Severity.ERROR,
                        message=f"Resource missing required field: '{field_name}'",
                        path=f"{path}.{field_name}",
                    ))

            # Check for duplicates
            rtype = resource.get("type", "unknown")
            rname = resource.get("name", "unknown")
            rmodule = resource.get("module", "")
            key = f"{rmodule}:{rtype}.{rname}"

            if key in seen:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Duplicate resource: {rtype}.{rname}",
                    path=path,
                    suggestion=f"Also found at $.resources[{seen[key][0]}]",
                ))
            else:
                seen[key] = []
            seen[key].append(i)

            # Check instances
            instances = resource.get("instances", [])
            if not isinstance(instances, list):
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"'instances' must be an array for {rtype}.{rname}",
                    path=f"{path}.instances",
                ))
            elif len(instances) == 0:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"Resource {rtype}.{rname} has no instances",
                    path=f"{path}.instances",
                    suggestion="This may indicate the resource was removed but not cleaned up",
                ))

        return issues

    def _check_outputs(self, state: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        outputs = state.get("outputs", {})

        if not isinstance(outputs, dict):
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                message="'outputs' must be an object",
                path="$.outputs",
            ))
            return issues

        for name, output in outputs.items():
            path = f"$.outputs.{name}"
            if not isinstance(output, dict):
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Output '{name}' must be an object",
                    path=path,
                ))
                continue

            if "value" not in output:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"Output '{name}' has no value",
                    path=f"{path}.value",
                ))

            # Warn about sensitive outputs without the sensitive flag
            if output.get("type") == "string":
                value = str(output.get("value", ""))
                sensitive_keywords = ("password", "secret", "token", "key", "credential")
                if any(kw in name.lower() for kw in sensitive_keywords):
                    if not output.get("sensitive", False):
                        issues.append(ValidationIssue(
                            severity=Severity.WARNING,
                            message=f"Output '{name}' looks sensitive but 'sensitive' flag is not set",
                            path=path,
                            suggestion="Set 'sensitive = true' in the output block",
                        ))

        return issues

    def _check_terraform_version(self, state: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        version = state.get("terraform_version")

        if version is None:
            issues.append(ValidationIssue(
                severity=Severity.INFO,
                message="Missing 'terraform_version' field",
                path="$.terraform_version",
            ))
        elif not isinstance(version, str):
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                message=f"'terraform_version' should be a string, got {type(version).__name__}",
                path="$.terraform_version",
            ))

        return issues

    def _check_providers(self, state: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resources = state.get("resources", [])

        if not isinstance(resources, list):
            return issues

        providers: set[str] = set()
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            provider = resource.get("provider", "")
            if provider:
                providers.add(provider)

        if not providers:
            issues.append(ValidationIssue(
                severity=Severity.INFO,
                message="No provider references found in resources",
            ))

        return issues
