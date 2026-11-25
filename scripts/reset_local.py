"""DESTRUCTIVE: reset local pipeline state (object store bucket, ingestion metadata, local warehouse).

    python scripts/reset_local.py            # asks for confirmation
    python scripts/reset_local.py --yes      # non-interactive (used by `make reset CONFIRM=yes`)

Source systems (ERP PostgreSQL schema, source_drop files) are NOT touched unless --sources is given.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finance_common.config import local_config, repo_path
from finance_common.storage import S3ObjectStore, object_store_from_config


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    p.add_argument("--sources", action="store_true", help="also drop the ERP schema and source_drop folder")
    args = p.parse_args()
    cfg = local_config()
    targets = [
        f"object store bucket '{cfg['object_store']['bucket']}' (all objects and versions)",
        "ingestion metadata (watermarks, batches, file registry)",
        f"local warehouse {cfg['paths']['warehouse_db']} and published snapshot",
    ]
    if args.sources:
        targets += ["ERP source schema in PostgreSQL", "sample_data/source_drop"]
    print("This will permanently delete:\n  - " + "\n  - ".join(targets))
    if not args.yes and input("Type 'reset' to continue: ").strip() != "reset":
        print("Aborted.")
        return
    store = object_store_from_config()
    if isinstance(store, S3ObjectStore):
        c = store.client
        names = {b["Name"] for b in c.list_buckets().get("Buckets", [])}
        if store.bucket in names:
            paginator = c.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=store.bucket):
                objs = [
                    {"Key": v["Key"], "VersionId": v["VersionId"]}
                    for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
                ]
                for i in range(0, len(objs), 1000):
                    c.delete_objects(Bucket=store.bucket, Delete={"Objects": objs[i : i + 1000], "Quiet": True})
            c.delete_bucket(Bucket=store.bucket)
    else:
        shutil.rmtree(store.root, ignore_errors=True)
    meta = cfg["metadata_db"]
    if meta["backend"] == "postgres":
        import psycopg

        pg = cfg["source_postgres"]
        with psycopg.connect(
            host=pg["host"],
            port=int(pg["port"]),
            dbname=pg["database"],
            user=pg["user"],
            password=pg["password"],
            autocommit=True,
        ) as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {meta['schema']} CASCADE")
            if args.sources:
                conn.execute("DROP SCHEMA IF EXISTS erp CASCADE")
    else:
        repo_path(meta["sqlite_path"]).unlink(missing_ok=True)
    for key in ("warehouse_db", "published_db"):
        path = repo_path(cfg["paths"][key])
        for f in (path, path.with_suffix(path.suffix + ".wal")):
            f.unlink(missing_ok=True)
    if args.sources:
        shutil.rmtree(repo_path(cfg["paths"]["source_drop"]), ignore_errors=True)
    print("Local state reset.")


if __name__ == "__main__":
    main()
