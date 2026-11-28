"""Private FastAPI transport for the MarketStudio V3 transaction slice."""
import json
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.db import init_db
from app.domain import DomainError
from app.service import BaselineService, SYNTHETIC_PRINCIPALS


class Item(BaseModel):
    item: dict[str, Any]
    request_id: str


class Items(BaseModel):
    items: list[dict[str, Any]]
    request_id: str


class Report(BaseModel):
    report: dict[str, Any]
    request_id: str


class Error(BaseModel):
    code: str
    message: str
    field_errors: dict[str, str]
    request_id: str


def local_settings():
    if os.environ.get("MARKETSTUDIO_ENV") not in {"development", "test"}:
        raise RuntimeError("V3 requires explicit local mode until production authentication is available.")
    for key in os.environ:
        if key.startswith("MARKETSTUDIO_") and any(flag in key for flag in ("STUB", "BOOTSTRAP", "DATABASE_URL")):
            raise RuntimeError(f"Unsupported V3 setting: {key}")
    db = Path(os.environ["MARKETSTUDIO_V3_SQLITE"]).expanduser().resolve()
    config_file = Path(os.environ["MARKETSTUDIO_V3_IDENTITIES"]).expanduser()
    try:
        if config_file.stat().st_mode & 0o077:
            raise ValueError
        identities = json.loads(config_file.read_text())
        if not isinstance(identities, dict) or not identities or any(
            not isinstance(secret, str) or len(secret) < 24
            or not name or name.strip() != name or name in SYNTHETIC_PRINCIPALS
            or secret in SYNTHETIC_PRINCIPALS.values()
            for name, secret in identities.items()
        ) or len(set(identities.values())) != len(identities):
            raise ValueError
    except (ValueError, OSError):
        raise RuntimeError("Configure private local identities with unique non-synthetic credentials.") from None
    return db, identities


@asynccontextmanager
async def lifespan(app: FastAPI):
    db, identities = local_settings()
    service = BaselineService(str(db), backend="sqlite", session_principals=identities)
    init_db(service.db_config)
    with service._tx(immediate=True) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS v3_worksheets (
                workspace_id TEXT PRIMARY KEY REFERENCES workspaces(workspace_id),
                cells_json TEXT NOT NULL,
                revision INTEGER NOT NULL
            )
        """)
    app.state.service = service
    app.state.identities = frozenset(identities)
    try:
        yield
    finally:
        service.close()


app = FastAPI(
    title="MarketStudio V3",
    lifespan=lifespan,
    redirect_slashes=False,
    responses={422: {"model": Error}, 401: {"model": Error}, 403: {"model": Error}, 409: {"model": Error}},
)


@app.middleware("http")
async def request_metadata(request: Request, call_next):
    request.state.request_id = f"req_{uuid4().hex[:10]}"
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(DomainError)
async def domain_error(request: Request, exc: DomainError):
    body = Error(code=exc.code, message=exc.message, field_errors=exc.field_errors, request_id=request.state.request_id)
    return JSONResponse(body.model_dump(), status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        return await domain_error(request, DomainError(404, "not_found", "Endpoint tidak ditemukan."))
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    response = await domain_error(request, DomainError(500, "internal_error", "Operasi gagal. Coba lagi."))
    response.headers["Cache-Control"] = "no-store"
    return response


async def payload(request: Request):
    try:
        length = int(request.headers.get("content-length", "0"))
        if not 0 <= length <= 1048576:
            raise ValueError
    except ValueError:
        raise DomainError(400, "invalid_content_length", "Content-Length di luar batas (0..1MB).") from None
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1048576:
            raise DomainError(400, "invalid_content_length", "Content-Length di luar batas (0..1MB).")
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError(422, "invalid_json", f"Body UTF-8/JSON tidak valid: {exc}") from exc
    if not isinstance(data, dict):
        raise DomainError(422, "invalid_json", "Body JSON harus berupa object.")
    return data


def actor(request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else request.headers.get("x-session-token")
    principal = request.app.state.service.resolve_session(token)
    if principal not in request.app.state.identities:
        raise DomainError(401, "unauthenticated", "Session tidak valid atau telah dicabut.")
    return principal


def reply(request: Request, status: int, **data):
    return JSONResponse({**data, "request_id": request.state.request_id}, status_code=status)


def body_schema(*fields: str):
    return {"requestBody": {"content": {"application/json": {"schema": {
        "type": "object", "description": "Validasi domain mempertahankan kontrak baseline.",
        "properties": {field: {} for field in fields},
    }}}}}


@app.get("/health")
def health():
    return {"status": "ok", "service": "marketstudio-v3", "db_backend": "sqlite"}


@app.post("/v1/sessions", response_model=Item, status_code=201, openapi_extra=body_schema("actor_id", "passcode"))
def create_session(request: Request, data: dict = Depends(payload)):
    result = request.app.state.service.create_session(data.get("actor_id", ""), data.get("passcode", ""))
    return reply(request, 201, item=result)


@app.get("/v1/workspaces", response_model=Items)
def workspaces(request: Request, principal: str = Depends(actor)):
    return reply(request, 200, items=request.app.state.service.list_workspaces(principal))


@app.post("/v1/workspaces", response_model=Item, status_code=201, openapi_extra=body_schema("name", "business_type", "timezone"))
def create_workspace(request: Request, principal: str = Depends(actor), data: dict = Depends(payload)):
    status, result = request.app.state.service.create_workspace(data, request.headers.get("idempotency-key"), principal)
    return reply(request, status, item=result)


@app.get("/v1/workspaces/{workspace_id}/offerings", response_model=Items)
def offerings(request: Request, workspace_id: str, principal: str = Depends(actor)):
    status = parse_qs(request.url.query).get("status", [None])[0]
    result = request.app.state.service.list_offerings(workspace_id, principal, status=status)
    return reply(request, 200, items=result)


def write(request, operation, workspace_id, principal, data):
    method = getattr(request.app.state.service, operation)
    status, result = method(workspace_id, principal, data, request.headers.get("idempotency-key"), actor=principal)
    return reply(request, status, item=result)


@app.post("/v1/workspaces/{workspace_id}/offerings", response_model=Item, status_code=201,
          openapi_extra=body_schema("name", "offering_type", "unit", "unit_price_idr"))
def create_offering(request: Request, workspace_id: str, principal: str = Depends(actor), data: dict = Depends(payload)):
    return write(request, "create_offering", workspace_id, principal, data)


@app.post("/v1/workspaces/{workspace_id}/purchases", response_model=Item, status_code=201,
          openapi_extra=body_schema("offering_id", "qty", "total_cost_idr", "payment_method", "occurred_at"))
def create_purchase(request: Request, workspace_id: str, principal: str = Depends(actor), data: dict = Depends(payload)):
    return write(request, "create_purchase", workspace_id, principal, data)


@app.post("/v1/workspaces/{workspace_id}/sales", response_model=Item, status_code=201,
          openapi_extra=body_schema("lines", "payment_method", "occurred_at"))
def create_sale(request: Request, workspace_id: str, principal: str = Depends(actor), data: dict = Depends(payload)):
    return write(request, "create_sale", workspace_id, principal, data)


@app.get("/v1/workspaces/{workspace_id}/reports/daily", response_model=Report)
def daily_report(request: Request, workspace_id: str, principal: str = Depends(actor)):
    date = parse_qs(request.url.query).get("date", [None])[0]
    result = request.app.state.service.get_daily_report(workspace_id, principal, date_str=date)
    return reply(request, 200, report=result)


def validate_worksheet(data: dict) -> tuple[int, str]:
    def invalid():
        return DomainError(422, "invalid_worksheet", "Isi lembar kerja tidak valid.")

    def index(value: str, limit: int) -> bool:
        return value.isascii() and value.isdecimal() and len(value) <= 2 and (
            int(value) < limit and str(int(value)) == value
        )

    cells, revision = data.get("cells"), data.get("revision")
    if set(data) != {"cells", "revision"} or type(revision) is not int or revision < 0 or not isinstance(cells, dict):
        raise invalid()
    for row, columns in cells.items():
        if not index(row, 100) or not isinstance(columns, dict):
            raise invalid()
        for column, cell in columns.items():
            if not index(column, 26) or not isinstance(cell, dict) or not cell or cell.keys() - {"v", "t", "f"}:
                raise invalid()
            value, kind, formula = cell.get("v"), cell.get("t"), cell.get("f")
            if (
                ("v" in cell and not (
                    type(value) is bool or isinstance(value, str) and len(value) <= 4096
                    or type(value) is int and abs(value) <= 2**53 - 1
                    or type(value) is float and math.isfinite(value)
                ))
                or ("t" in cell and (type(kind) is not int or kind not in {1, 2, 3, 4}))
                or ("f" in cell and (not isinstance(formula, str) or not formula.startswith("=") or len(formula) > 4096))
                or cell.keys().isdisjoint({"v", "f"})
            ):
                raise invalid()
    try:
        encoded = json.dumps(cells, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        encoded.encode("utf-8")
    except UnicodeEncodeError:
        raise invalid() from None
    return revision, encoded


@app.get("/v1/workspaces/{workspace_id}/worksheet", response_model=Item)
def load_worksheet(request: Request, workspace_id: str, principal: str = Depends(actor)):
    service = request.app.state.service
    with service._tx() as conn:
        role = service._assert_workspace_access(conn, workspace_id, principal)
        row = conn.execute(
            "SELECT cells_json, revision FROM v3_worksheets WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
    return reply(request, 200, item={
        "cells": json.loads(row["cells_json"]) if row else {},
        "revision": row["revision"] if row else 0,
        "can_edit": role == "owner",
    })


@app.put("/v1/workspaces/{workspace_id}/worksheet", response_model=Item,
         openapi_extra=body_schema("cells", "revision"))
def save_worksheet(request: Request, workspace_id: str, principal: str = Depends(actor),
                   data: dict = Depends(payload)):
    service = request.app.state.service
    with service._tx(immediate=True) as conn:
        if service._assert_workspace_access(conn, workspace_id, principal) != "owner":
            raise DomainError(403, "forbidden", "Hanya pemilik ruang kerja yang dapat menyimpan lembar kerja.")
        expected_revision, cells = validate_worksheet(data)
        row = conn.execute(
            "SELECT cells_json, revision FROM v3_worksheets WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()
        revision = row["revision"] if row else 0
        if row and row["cells_json"] == cells:
            return reply(request, 200, item={"revision": revision})
        if revision != expected_revision:
            raise DomainError(409, "worksheet_conflict", "Lembar kerja telah berubah. Salin edit Anda sebelum membuka ulang.")
        revision += 1
        conn.execute("""
            INSERT INTO v3_worksheets (workspace_id, cells_json, revision) VALUES (?, ?, ?)
            ON CONFLICT (workspace_id) DO UPDATE SET cells_json = excluded.cells_json, revision = excluded.revision
        """, (workspace_id, cells, revision))
    return reply(request, 200, item={"revision": revision})
