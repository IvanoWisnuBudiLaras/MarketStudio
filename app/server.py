"""HTTP server for MarketStudio Issue #5 runnable baseline."""

from __future__ import annotations

import json
import os
import re
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.db import DEFAULT_DB_PATH, init_db
from app.domain import DomainError
from app.service import BaselineService

WEB_INDEX_PATH = Path(__file__).resolve().parent / "web" / "index.html"
_RE_OFFERINGS = re.compile(r"^/v1/workspaces/([^/]+)/offerings$")
_RE_OFFERING_DETAIL = re.compile(r"^/v1/workspaces/([^/]+)/offerings/([^/]+)$")
_RE_PURCHASES = re.compile(r"^/v1/workspaces/([^/]+)/purchases$")
_RE_SALES = re.compile(r"^/v1/workspaces/([^/]+)/sales$")
_RE_REPORT_DAILY = re.compile(r"^/v1/workspaces/([^/]+)/reports/daily$")


class BaselineHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler serving the single browser entry point and /v1 JSON API."""

    service: BaselineService  # injected on server class

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Keep test output clean; server logs can be enabled via env if needed.
        if os.environ.get("MARKETSTUDIO_QUIET_LOGS") == "1":
            return
        super().log_message(format, *args)

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_envelope(self, err: DomainError, request_id: str) -> None:
        self._send_json(
            err.status_code,
            {
                "code": err.code,
                "message": err.message,
                "field_errors": err.field_errors,
                "request_id": request_id,
            },
        )

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DomainError(422, "invalid_json", f"JSON tidak valid: {exc}") from exc
        if not isinstance(data, dict):
            raise DomainError(422, "invalid_json", "Body JSON harus berupa object.")
        return data

    def _require_actor(self) -> str:
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else self.headers.get("X-Session-Token")
        return self.service.resolve_session(token)

    def do_GET(self) -> None:  # noqa: N802
        request_id = f"req_{uuid.uuid4().hex[:10]}"
        path = urlparse(self.path).path

        try:
            if path == "/" or path == "/index.html":
                html = WEB_INDEX_PATH.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            if path == "/health":
                self._send_json(200, {"status": "ok", "service": "marketstudio-baseline"})
                return

            if path == "/v1/workspaces":
                actor_id = self._require_actor()
                items = self.service.list_workspaces(actor_id)
                self._send_json(200, {"items": items, "request_id": request_id})
                return

            m_list = _RE_OFFERINGS.match(path)
            if m_list:
                actor_id = self._require_actor()
                ws_id = m_list.group(1)
                actor_status = self.headers.get("X-Actor-Status")
                items = self.service.list_offerings(ws_id, actor_id, actor_status=actor_status)
                self._send_json(200, {"items": items, "request_id": request_id})
                return

            m_detail = _RE_OFFERING_DETAIL.match(path)
            if m_detail:
                actor_id = self._require_actor()
                ws_id, off_id = m_detail.group(1), m_detail.group(2)
                actor_status = self.headers.get("X-Actor-Status")
                item = self.service.get_offering(ws_id, off_id, actor_id, actor_status=actor_status)
                self._send_json(200, {"item": item, "request_id": request_id})
                return

            m_report = _RE_REPORT_DAILY.match(path)
            if m_report:
                actor_id = self._require_actor()
                ws_id = m_report.group(1)
                actor_status = self.headers.get("X-Actor-Status")
                qs = parse_qs(urlparse(self.path).query)
                date_str = qs.get("date", [None])[0]
                report = self.service.get_daily_report(
                    ws_id, actor_id, date_str=date_str, actor_status=actor_status
                )
                self._send_json(200, {"report": report, "request_id": request_id})
                return

            self._send_error_envelope(DomainError(404, "not_found", "Endpoint tidak ditemukan."), request_id)
        except DomainError as err:
            self._send_error_envelope(err, request_id)

    def do_POST(self) -> None:  # noqa: N802
        request_id = f"req_{uuid.uuid4().hex[:10]}"
        path = urlparse(self.path).path
        idem_key = self.headers.get("Idempotency-Key")

        try:
            if path == "/v1/sessions":
                body = self._read_json_body()
                session = self.service.create_session(body.get("actor_id", ""))
                self._send_json(201, {"item": session, "request_id": request_id})
                return

            if path == "/v1/workspaces":
                actor_id = self._require_actor()
                body = self._read_json_body()
                status, item = self.service.create_workspace(body, idempotency_key=idem_key, actor=actor_id)
                self._send_json(status, {"item": item, "request_id": request_id})
                return

            m_list = _RE_OFFERINGS.match(path)
            if m_list:
                actor_id = self._require_actor()
                ws_id = m_list.group(1)
                actor_status = self.headers.get("X-Actor-Status")
                body = self._read_json_body()
                status, item = self.service.create_offering(
                    ws_id,
                    caller_workspace_id=actor_id,
                    payload=body,
                    idempotency_key=idem_key,
                    actor=actor_id,
                    actor_status=actor_status,
                )
                self._send_json(status, {"item": item, "request_id": request_id})
                return

            m_pur = _RE_PURCHASES.match(path)
            if m_pur:
                actor_id = self._require_actor()
                ws_id = m_pur.group(1)
                actor_status = self.headers.get("X-Actor-Status")
                body = self._read_json_body()
                status, item = self.service.create_purchase(
                    ws_id,
                    caller_workspace_id=actor_id,
                    payload=body,
                    idempotency_key=idem_key,
                    actor=actor_id,
                    actor_status=actor_status,
                )
                self._send_json(status, {"item": item, "request_id": request_id})
                return

            m_sale = _RE_SALES.match(path)
            if m_sale:
                actor_id = self._require_actor()
                ws_id = m_sale.group(1)
                actor_status = self.headers.get("X-Actor-Status")
                body = self._read_json_body()
                status, item = self.service.create_sale(
                    ws_id,
                    caller_workspace_id=actor_id,
                    payload=body,
                    idempotency_key=idem_key,
                    actor=actor_id,
                    actor_status=actor_status,
                )
                self._send_json(status, {"item": item, "request_id": request_id})
                return

            self._send_error_envelope(DomainError(404, "not_found", "Endpoint tidak ditemukan."), request_id)
        except DomainError as err:
            self._send_error_envelope(err, request_id)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: str = DEFAULT_DB_PATH,
) -> ThreadingHTTPServer:
    """Create configured ThreadingHTTPServer for MarketStudio baseline."""
    init_db(db_path)
    service = BaselineService(db_path=db_path)

    class _Handler(BaselineHTTPHandler):
        pass

    _Handler.service = service
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> None:
    host = os.environ.get("MARKETSTUDIO_HOST", "127.0.0.1")
    port = int(os.environ.get("MARKETSTUDIO_PORT", "8000"))
    db_path = os.environ.get("MARKETSTUDIO_DB_PATH", DEFAULT_DB_PATH)
    server = create_server(host=host, port=port, db_path=db_path)
    print(f"MarketStudio baseline running at http://{host}:{port} (db: {db_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
