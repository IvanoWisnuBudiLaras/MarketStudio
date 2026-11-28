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
            ai_rev = check(client.post(f"{path}/reports/daily/ai-review", json={}, headers=headers), 200)["item"]
            self.assertTrue(ai_rev["read_only"])
            self.assertEqual(ai_rev["status"], "fallback")
            cfg = check(client.get(f"{path}/ai-review/config", headers=headers), 200)["item"]
            self.assertIn("configured", cfg)
            return cases, metrics

        legacy_actor, legacy_password = next(iter(SYNTHETIC_PRINCIPALS.items()))
        self.assertEqual(run(self.old, legacy_actor, legacy_password), run(self.new, "authorized", self.credentials["authorized"]))

    def test_ai_review_tenant_isolation_and_auth(self):
        def headers_for(identity):
            session = self.new.post("/v1/sessions", json={
                "actor_id": identity, "passcode": self.credentials[identity],
            }).json()["item"]
            return {"X-Session-Token": session["token"]}

        headers = headers_for("authorized")
        workspace = self.new.post("/v1/workspaces", headers=headers, json={"name": "Warung Padi"}).json()["item"]
        path = f"/v1/workspaces/{workspace['workspace_id']}"

        # 401 unauthenticated
        self.assertEqual(self.new.post(f"{path}/reports/daily/ai-review", json={}).status_code, 401)
        self.assertEqual(self.new.get(f"{path}/ai-review/config").status_code, 401)

        # 404 non-member (anti-enumeration)
        other = headers_for("other")
        self.assertEqual(self.new.post(f"{path}/reports/daily/ai-review", json={}, headers=other).status_code, 404)
        self.assertEqual(self.new.get(f"{path}/ai-review/config", headers=other).status_code, 404)

        # 200 authorized
        res = self.new.post(f"{path}/reports/daily/ai-review", json={}, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["item"]["read_only"])
        self.assertTrue(res.json()["item"]["ledger_unchanged"])

    def test_worksheet_validation_and_revisions(self):
        def headers_for(identity):
            session = self.new.post("/v1/sessions", json={
                "actor_id": identity, "passcode": self.credentials[identity],
            }).json()["item"]
            return {"X-Session-Token": session["token"]}

        headers = headers_for("authorized")
        workspace = self.new.post("/v1/workspaces", headers=headers, json={"name": "Warung Padi"}).json()["item"]
        path = f"/v1/workspaces/{workspace['workspace_id']}/worksheet"
        self.assertEqual(self.new.get(path).status_code, 401)
        self.assertEqual(self.new.put(path, json={}).status_code, 401)
        self.assertEqual(self.new.get(path, headers=headers).json()["item"],
                         {"cells": {}, "revision": 0, "can_edit": True})

        for cells in (
            {"100": {"0": {"v": 1}}}, {"0": {"26": {"v": 1}}},
            {"0": {"0": {"p": {"arbitrary": "data"}}}}, {"0": {"0": {"v": [1]}}},
        ):
            self.assertEqual(self.new.put(path, headers=headers, json={"cells": cells, "revision": 0}).status_code, 422)

        draft = {"cells": {"0": {"0": {"v": "Rencana", "t": 1}, "1": {"f": "=1+2"}}}, "revision": 0}
        for _ in range(2):
            saved = self.new.put(path, headers=headers, json=draft)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["item"], {"revision": 1})
        self.assertEqual(self.new.put(path, headers=headers, json={"cells": {}, "revision": 0}).status_code, 409)

        other = headers_for("other")
        self.assertEqual(self.new.get(path, headers=other).status_code, 404)
        self.assertEqual(self.new.put(path, headers=other, json=draft).status_code, 404)
        app.state.service.add_membership(workspace["workspace_id"], "other")
        self.assertFalse(self.new.get(path, headers=other).json()["item"]["can_edit"])
        self.assertEqual(self.new.put(path, headers=other, json=draft).status_code, 403)
        app.state.service.revoke_membership(workspace["workspace_id"], "other")
        self.assertEqual(self.new.get(path, headers=other).status_code, 404)
        self.assertEqual(self.new.get(path, headers=headers).json()["item"]["cells"], draft["cells"])

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
