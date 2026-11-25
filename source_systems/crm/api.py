"""Simulated CRM REST API (stdlib HTTP server, no framework dependency).

GET /api/v1/health
GET /api/v1/<resource>?updated_since=<iso-ts>&page_size=<n>&cursor=<token>
    resources: customers, customer_history, opportunities, sales_orders, revenue_forecasts

* Returns the current version of each record whose ``updated_at`` > ``updated_since``.
* Keyset pagination: results ordered by (updated_at, primary key); ``next_cursor`` encodes the last
  key returned, so pages are stable even if new records arrive between calls.
* ``FDW_CRM_FAILURE_RATE`` (0..1) makes a share of requests fail with HTTP 503 to exercise
  client-side retries with exponential backoff; ``FDW_CRM_API_KEY`` enables bearer-token auth.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import threading
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import duckdb

from finance_common import contracts
from source_systems.common import source_drop_dir

RESOURCES = {t.name: t for t in contracts.tables_for("crm")}
MAX_PAGE = 2000


def _json_default(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    raise TypeError(type(v))


class CrmStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._lock = threading.Lock()
        self._con = duckdb.connect()
        self._con.execute("SET TimeZone = 'UTC'")
        self._loaded: dict[str, float] = {}

    def _materialize(self, resource: str, path: Path, pk: list[str]) -> str:
        """Latest version per key, sorted by the pagination key; rebuilt only when the file changes."""
        mtime = path.stat().st_mtime
        table = f"latest_{resource}"
        if self._loaded.get(resource) != mtime:
            keys = ", ".join(f'"{k}"' for k in pk)
            self._con.execute(
                f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet('{path.as_posix()}') "
                f"QUALIFY row_number() OVER (PARTITION BY {keys} ORDER BY updated_at DESC) = 1 "
                f"ORDER BY updated_at, {keys}"
            )
            self._loaded[resource] = mtime
        return table

    def page(self, resource: str, updated_since: str | None, cursor: str | None, page_size: int) -> dict[str, Any]:
        t = RESOURCES[resource]
        path = self.data_dir / f"{resource}.parquet"
        if not path.exists():
            return {"data": [], "next_cursor": None}
        pk = list(t.primary_key)
        order = ", ".join(['"updated_at"', *[f'"{k}"' for k in pk]])
        where, params = [], {}
        if updated_since:
            where.append('"updated_at" > $since')
            params["since"] = datetime.fromisoformat(updated_since)
        if cursor:
            last = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            cols = ", ".join(['"updated_at"', *[f'"{k}"' for k in pk]])
            ph = ", ".join(f"$c{i}" for i in range(len(last)))
            where.append(f"({cols}) > ({ph})")
            types = {c.name: c.type for c in t.columns}
            for i, (name, v) in enumerate(zip(["updated_at", *pk], last, strict=True)):
                params[f"c{i}"] = (
                    datetime.fromisoformat(v) if types[name] == "ts" else (int(v) if types[name] == "int" else v)
                )
        with self._lock:
            table = self._materialize(resource, path, pk)
            sql = f"SELECT * FROM {table} {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY {order} LIMIT {page_size + 1}"
            rel = self._con.execute(sql, params)
            names = [d[0] for d in rel.description]
            rows = [dict(zip(names, r, strict=True)) for r in rel.fetchall()]
        next_cursor = None
        if len(rows) > page_size:
            rows = rows[:page_size]
            key = [rows[-1]["updated_at"].isoformat(), *[rows[-1][k] for k in pk]]
            next_cursor = base64.urlsafe_b64encode(json.dumps(key, default=_json_default).encode()).decode()
        return {"data": rows, "next_cursor": next_cursor}


def make_handler(store: CrmStore, failure_rate: float, api_key: str | None) -> type[BaseHTTPRequestHandler]:
    rng = random.Random(7)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # structured, quiet logs
            pass

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, default=_json_default).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            parts = [p for p in url.path.split("/") if p]
            if parts == ["api", "v1", "health"]:
                self._send(200, {"status": "ok"})
                return
            if api_key and self.headers.get("Authorization") != f"Bearer {api_key}":
                self._send(401, {"error": "unauthorized"})
                return
            if len(parts) != 3 or parts[:2] != ["api", "v1"] or parts[2] not in RESOURCES:
                self._send(404, {"error": "unknown resource"})
                return
            if failure_rate and rng.random() < failure_rate:
                self._send(503, {"error": "service temporarily unavailable"})
                return
            q = parse_qs(url.query)
            try:
                size = min(MAX_PAGE, max(1, int(q.get("page_size", ["500"])[0])))
                result = store.page(parts[2], q.get("updated_since", [None])[0], q.get("cursor", [None])[0], size)
            except (ValueError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)})
                return
            except Exception as exc:  # never drop the connection: report a retryable server error
                self._send(500, {"error": f"internal error: {type(exc).__name__}"})
                return
            self._send(200, {"resource": parts[2], "count": len(result["data"]), **result})

    return Handler


def serve(
    host: str, port: int, data_dir: Path, failure_rate: float = 0.0, api_key: str | None = None
) -> ThreadingHTTPServer:
    class Server(ThreadingHTTPServer):
        # On Windows SO_REUSEADDR lets a second process bind the same port silently; fail fast instead.
        allow_reuse_address = os.name != "nt"
        daemon_threads = True

    return Server((host, port), make_handler(CrmStore(data_dir), failure_rate, api_key))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8085)
    args = p.parse_args()
    data_dir = Path(os.environ.get("FDW_CRM_DATA_DIR", str(source_drop_dir() / "crm")))
    server = serve(
        args.host,
        args.port,
        data_dir,
        float(os.environ.get("FDW_CRM_FAILURE_RATE", "0")),
        os.environ.get("FDW_CRM_API_KEY"),
    )
    print(f"CRM API listening on http://{args.host}:{args.port} (data: {data_dir})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
