"""Private FastAPI transport for the MarketStudio V3 transaction slice."""
import json
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
