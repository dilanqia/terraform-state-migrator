# terraform-state-migrator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

CLI tool to safely migrate Terraform state between backends with validation, locking, and rollback support.

## Features

- 🔄 **S3-to-S3 Migration** — copy state between S3 buckets with key prefix mapping
- ✅ **State Validation** — verify resource counts, outputs, and serial numbers before migration
- 🔒 **Lock Handling** — respect and manage state locks during migration
- 📋 **Dry Run Mode** — preview changes before executing
- 🎨 **Rich Output** — colored terminal output with progress bars

## Installation

```bash
pip install terraform-state-migrator
```

Or from source:

```bash
git clone https://github.com/dilanqia/terraform-state-migrator.git
cd terraform-state-migrator
pip install -e ".[dev]"
```

## Usage

### Migrate S3 to S3

```bash
tf-migrate s3-to-s3 \
  --source-bucket my-terraform-state \
  --source-key envs/prod/terraform.tfstate \
  --dest-bucket new-terraform-state \
  --dest-key prod/terraform.tfstate \
  --source-region us-east-1 \
  --dest-region us-west-2
```

### Dry Run

```bash
tf-migrate s3-to-s3 \
  --source-bucket my-state \
  --source-key terraform.tfstate \
  --dest-bucket new-state \
  --dest-key terraform.tfstate \
  --dry-run
```

### Validate State

```bash
tf-migrate validate --bucket my-state --key terraform.tfstate
```

## Validation Checks

| Check | Description |
|-------|-------------|
| Resource Count | Ensures source and dest have same number of resources |
| Serial Number | Verifies dest serial >= source serial |
| Output Keys | Confirms all outputs are preserved |
| Lock Status | Checks for existing locks before migration |
| State Version | Validates Terraform state format version |

## API Usage

```python
from migrator.s3_to_s3 import S3BackendMigrator
from migrator.validate import StateValidator

migrator = S3BackendMigrator(
    source_bucket="old-state",
    source_key="terraform.tfstate",
    dest_bucket="new-state",
    dest_key="terraform.tfstate",
)

# Validate first
validator = StateValidator(migrator)
report = validator.validate()
if report.is_valid:
    migrator.migrate()
```

## Contributing

Contributions welcome! Please open an issue or PR.

## License

[MIT](LICENSE)

<!-- history: 2026-06-01 -->

<!-- history: 2026-06-04 -->

<!-- history: 2026-06-04 -->

<!-- history: 2026-06-05 -->

<!-- history: 2026-06-05 -->

<!-- history: 2026-06-06 -->
