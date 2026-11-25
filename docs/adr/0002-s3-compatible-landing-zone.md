# ADR 0002: S3-compatible landing zone with manifests

**Status:** accepted

## Context
Ingestion and loading must be decoupled, replayable and idempotent. The usual local S3 emulator (MinIO)
images could not be pulled in the development environment.

## Decision
All extractors write Parquet batches to an S3 API: SeaweedFS locally, AWS S3 in the cloud, and a filesystem
store for tests. Each batch has a JSON manifest (row count, checksum, watermark range). The raw loader
loads each manifest exactly once and records it in `raw_load_history`. A watermark advances only after
its manifest has been written.

## Consequences
* A crash between extract and load loses nothing. Re-running the loader is a no-op
  (`tests/end_to_end/test_idempotency.py`).
* The 120-minute watermark overlap means some rows are extracted twice, and staging dedupes them by version.
* Swapping SeaweedFS for MinIO or S3 is a configuration change (`config/local.yaml`).
