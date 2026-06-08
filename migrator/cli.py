"""CLI entry point for terraform-state-migrator."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from migrator.s3_to_s3 import S3BackendConfig, S3BackendMigrator
from migrator.validate import StateValidator


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.group()
@click.version_option(package_name="terraform-state-migrator")
def cli() -> None:
    """Terraform state migration and validation tool.

    Migrate state files between S3 backends, validate state integrity,
    and manage state locking.
    """


@cli.command()
@click.argument("source_file", type=click.Path(exists=True))
@click.option("--strict", is_flag=True, help="Treat warnings as errors")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def validate(source_file: str, strict: bool,