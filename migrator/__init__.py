"""terraform-state-migrator — Migrate Terraform state between S3 backends."""

from migrator.s3_to_s3 import S3BackendConfig, S3BackendMigrator
from migrator.validate import StateValidator, ValidationResult

__version__ = "0.1.0"
__all__ = [
    "S3BackendConfig",
    "S3BackendMigrator",
    "StateValidator",
    "ValidationResult",
]
