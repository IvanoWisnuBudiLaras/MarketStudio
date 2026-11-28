"""Exercise FastAPI against the legacy transport contract on separate databases."""
import json
import os
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import httpx
    from fastapi.testclient import TestClient
    from app.v3 import app, local_settings
except ModuleNotFoundError as exc:
    if exc.name not in {"httpx", "fastapi"}:
        raise
    raise unittest.SkipTest("Install the v3 extra to exercise the FastAPI transport.") from exc

from app.server import create_server
from app.service import SYNTHETIC_PRINCIPALS


class TransportParity(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.credentials = {"authorized": secrets.token_urlsafe(32), "other": secrets.token_urlsafe(32)}
        identities = root / "identities.json"
        identities.touch(mode=0o600)
        identities.write_text(json.dumps(self.credentials))
        context = patch.dict(os.environ, MARKETSTUDIO_ENV="test", MARKETSTUDIO_V3_SQLITE=str(root / "new.sqlite"),
                             MARKETSTUDIO_V3_IDENTITIES=str(identities))
        self.addCleanup(context.stop)
        context.start()
        self.new = self.enterContext(TestClient(app, raise_server_exceptions=False))
        legacy = create_server(port=0, db_path=str(root / "legacy.sqlite"), quiet_logs=True)
        worker = threading.Thread(target=legacy.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(legacy.server_close)
        self.addCleanup(legacy.shutdown)
        self.old = self.enterContext(httpx.Client(base_url=f"http://127.0.0.1:{legacy.server_port}"))

    def test_errors_and_reports_match(self):
        def check(response, status):
            self.assertEqual(response.status_code, status, response.text)
            body = response.json()
            self.assertRegex(body.pop("request_id"), r"^req_[a-f0-9]{10}$")
            return body

        def run(client, identity, password):
            cases = [check(client.get("/v1/workspaces"), 401)]
            cases.append(check(client.post("/v1/sessions", content=b"[]"), 422))
            session = check(client.post("/v1/sessions", json={"actor_id": identity, "passcode": password}), 201)
            token = session["item"]["token"]
            headers = {"X-Session-Token": token}
            cases.append(check(client.get("/v1/workspaces", headers=headers), 200))
            cases.append(check(client.post("/v1/workspaces", json={"name": "x"}, headers=headers), 422))
            base = "/v1/workspaces"
            ws = check(client.post(base, json={"name": "Warung Padi"}, headers=headers), 201)["item"]
            path = f"{base}/{ws['workspace_id']}"
            product = {"name": "Beras medium", "offering_type": "goods", "unit": "kg", "unit_price_idr": 14500}
            item = check(client.post(f"{path}/offerings", json=product, headers=headers), 201)["item"]
            offering = item["offering_id"]
            check(client.post(f"{path}/purchases", json={"offering_id": offering, "qty": "10",
                  "total_cost_idr": 120000, "occurred_at": "2026-11-28T00:00:00+07:00"}, headers=headers), 201)
            with_key = {**headers, "Idempotency-Key": "parity-sale"}
            body = {"lines": [{"offering_id": offering, "qty": "2", "total_price_idr": 29000}],
                    "occurred_at": "2026-11-28T00:01:00+07:00"}
            sale = check(client.post(f"{path}/sales", json=body, headers=with_key), 201)
            self.assertEqual(check(client.post(f"{path}/sales", json=body, headers=with_key), 201), sale)
            body["lines"][0]["qty"] = "3"
            cases.append(check(client.post(f"{path}/sales", json=body, headers=with_key), 409))
            report = check(client.get(f"{path}/reports/daily?date=2026-11-28", headers=headers), 200)["report"]
            metrics = tuple(report[field] for field in ("revenue_idr", "cogs_idr", "gross_profit_idr", "net_cash_flow_idr"))
            self.assertEqual(metrics, (29000, 24000, 5000, -91000))
            inv = report["ending_inventory"]["items"][0]
            self.assertEqual((inv["qty_remaining"], inv["value_idr"]), ("8", 96000))
            self.assertEqual(len(report["drill_down"]["sales"]), 1)
            return cases, metrics

        legacy_actor, legacy_password = next(iter(SYNTHETIC_PRINCIPALS.items()))
        self.assertEqual(run(self.old, legacy_actor, legacy_password), run(self.new, "authorized", self.credentials["authorized"]))

    def test_production_fails_closed_and_no_demo_route(self):
        for mode in ("", "production", "typo"):
            with patch.dict(os.environ, MARKETSTUDIO_ENV=mode), self.assertRaises(RuntimeError):
                local_settings()
        for flag in ("MARKETSTUDIO_ENABLE_AI_STUBS", "MARKETSTUDIO_BOOTSTRAP", "MARKETSTUDIO_DATABASE_URL"):
            with patch.dict(os.environ, {flag: "1"}), self.assertRaises(RuntimeError):
                local_settings()
        actor, secret = next(iter(SYNTHETIC_PRINCIPALS.items()))
        result = self.new.post("/v1/sessions", json={"actor_id": actor, "passcode": secret})
        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(self.new.post("/v1/workspaces/demo").status_code, 404)
        self.assertNotIn("/v1/workspaces/demo", self.new.get("/openapi.json").json()["paths"])
