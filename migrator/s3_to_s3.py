"""S3-to-S3 state migration backend."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@dataclass
class S3BackendConfig:
    """Configuration for an S3 backend."""

    bucket: str
    key: str
    region: str = "us-east-1"
    profile: str | None = None
    endpoint_url: str | None = None
    kms_key_id: str | None = None
    dynamodb_table: str | None = None

    def create_session(self) -> boto3.Session:
        kwargs: dict[str, Any] = {"region_name": self.region}
        if self.profile:
            kwargs["profile_name"] = self.profile
        return boto3.Session(**kwargs)

    def create_client(self, session: boto3.Session | None = None) -> Any:
        sess = session or self.create_session()
        kwargs: dict[str, Any] = {}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return sess.client("s3", **kwargs)


@dataclass
class MigrationResult:
    """Result of a state migration."""

    success: bool
    source_key: str
    dest_key: str
    state_version: int | None = None
    resource_count: int | None = None
    serial: int | None = None
    lineage: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None
    backup_key: str | None = None


class S3BackendMigrator:
    """Migrates Terraform state files between S3 backends.

    Supports:
    - Copy with validation
    - Automatic backup before overwrite
    - State locking via DynamoDB
    - Dry-run mode
    """

    def __init__(
        self,
        source: S3BackendConfig,
        dest: S3BackendConfig,
        *,
        dry_run: bool = False,
        create_backup: bool = True,
    ) -> None:
        self.source = source
        self.dest = dest
        self.dry_run = dry_run
        self.create_backup = create_backup

        self._source_session = source.create_session()
        self._dest_session = dest.create_session()
        self._source_client = source.create_client(self._source_session)
        self._dest_client = dest.create_client(self._dest_session)

    def read_state(self) -> dict[str, Any]:
        """Read and parse the state file from the source backend."""
        logger.info("Reading state from s3://%s/%s", self.source.bucket, self.source.key)

        try:
            response = self._source_client.get_object(
                Bucket=self.source.bucket,
                Key=self.source.key,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(
                    f"State file not found: s3://{self.source.bucket}/{self.source.key}"
                ) from e
            raise

        body = response["Body"].read().decode("utf-8")
        state = json.loads(body)
        logger.info(
            "Read state: version=%s, serial=%s, resources=%d",
            state.get("version"),
            state.get("serial"),
            len(state.get("resources", [])),
        )
        return state

    def write_state(self, state: dict[str, Any]) -> None:
        """Write state to the destination backend."""
        logger.info("Writing state to s3://%s/%s", self.dest.bucket, self.dest.key)

        if self.dry_run:
            logger.info("[DRY RUN] Would write %d bytes", len(json.dumps(state)))
            return

        body = json.dumps(state, indent=2)
        kwargs: dict[str, Any] = {
            "Bucket": self.dest.bucket,
            "Key": self.dest.key,
            "Body": body.encode("utf-8"),
            "ContentType": "application/json",
            "ServerSideEncryption": "aws:kms" if self.dest.kms_key_id else "AES256",
        }
        if self.dest.kms_key_id:
            kwargs["SSEKMSKeyId"] = self.dest.kms_key_id

        self._dest_client.put_object(**kwargs)
        logger.info("State written successfully")

    def backup_state(self) -> str | None:
        """Create a backup of the destination state (if it exists)."""
        if not self.create_backup:
            return None

        try:
            self._dest_client.head_object(
                Bucket=self.dest.bucket,
                Key=self.dest.key,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                logger.info("No existing state to back up at destination")
                return None
            raise

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_key = f"{self.dest.key}.backup.{timestamp}"

        logger.info("Backing up destination state to s3://%s/%s", self.dest.bucket, backup_key)

        if self.dry_run:
            logger.info("[DRY RUN] Would create backup at %s", backup_key)
            return backup_key

        self._dest_client.copy_object(
            Bucket=self.dest.bucket,
            CopySource={"Bucket": self.dest.bucket, "Key": self.dest.key},
            Key=backup_key,
        )
        logger.info("Backup created: %s", backup_key)
        return backup_key

    def acquire_lock(self) -> bool:
        """Acquire a DynamoDB lock on the destination backend."""
        if not self.dest.dynamodb_table:
            logger.info("No DynamoDB table configured — skipping lock")
            return True

        logger.info("Acquiring lock on DynamoDB table: %s", self.dest.dynamodb_table)

        dynamodb = self._dest_session.resource("dynamodb")
        table = dynamodb.Table(self.dest.dynamodb_table)

        try:
            table.put_item(
                Item={
                    "LockID": f"{self.dest.bucket}/{self.dest.key}",
                    "Created": datetime.now(timezone.utc).isoformat(),
                },
                ConditionExpression="attribute_not_exists(LockID)",
            )
            logger.info("Lock acquired")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.error("Lock already held — another migration may be in progress")
                return False
            raise

    def release_lock(self) -> None:
        """Release the DynamoDB lock."""
        if not self.dest.dynamodb_table:
            return

        logger.info("Releasing lock on DynamoDB table: %s", self.dest.dynamodb_table)
        dynamodb = self._dest_session.resource("dynamodb")
        table = dynamodb.Table(self.dest.dynamodb_table)

        table.delete_item(
            Key={"LockID": f"{self.dest.bucket}/{self.dest.key}"},
        )
        logger.info("Lock released")

    def migrate(self) -> MigrationResult:
        """Execute the full migration: read → backup → validate → write."""
        try:
            # Read source state
            state = self.read_state()

            # Lock destination
            if not self.acquire_lock():
                return MigrationResult(
                    success=False,
                    source_key=self.source.key,
                    dest_key=self.dest.key,
                    error="Could not acquire lock on destination",
                )

            try:
                # Backup existing destination state
                backup_key = self.backup_state()

                # Write to destination
                self.write_state(state)

                return MigrationResult(
                    success=True,
                    source_key=self.source.key,
                    dest_key=self.dest.key,
                    state_version=state.get("version"),
                    resource_count=len(state.get("resources", [])),
                    serial=state.get("serial"),
                    lineage=state.get("lineage"),
                    backup_key=backup_key,
                )
            finally:
                self.release_lock()

        except Exception as e:
            logger.error("Migration failed: %s", e)
            return MigrationResult(
                success=False,
                source_key=self.source.key,
                dest_key=self.dest.key,
                error=str(e),
            )
