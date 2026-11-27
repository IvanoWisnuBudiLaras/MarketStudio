"""HTTP acceptance tests for the Creative Studio poster export."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

from app.creative import DEFAULT_ASSETS_DIR, decode_png_rgb
from app.db import db_transaction
from app.server import create_server


class PosterExportTest(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.db_path = str(Path(temp) / "poster.sqlite3")
        self.assets = Path(temp) / "assets"
        shutil.copytree(DEFAULT_ASSETS_DIR, self.assets)
        server = create_server(port=0, db_path=self.db_path, creative_assets_dir=self.assets)
        self.service = server.service
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}"
        self.owner = self.login("actor_a", "dev-a-pass")
        self.other = self.login("actor_b", "dev-b-pass")
        demo = self.item("POST", "/v1/workspaces/demo", self.owner, {}, 201)
        self.ws_id = demo["workspace"]["workspace_id"]
        self.root = f"/v1/workspaces/{self.ws_id}"
        self.draft = self.item("POST", self.root + "/creative-drafts/sample", self.owner, {}, 201)
        self.path = f"{self.root}/creative-drafts/{self.draft['draft_id']}"

    def request(self, method, path, token=None, body=None, headers=None):
        headers = dict(headers or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, response.headers, response.read()

    def item(self, method, path, token, body, expected_status):
        status, _, raw = self.request(method, path, token, body)
        self.assertEqual(status, expected_status, raw)
        return json.loads(raw)["item"]

    def login(self, actor_id, passcode):
        return self.item("POST", "/v1/sessions", None, {"actor_id": actor_id, "passcode": passcode}, 201)["token"]

    def preview(self, fmt="svg"):
        return self.item("POST", self.path + "/preview", self.owner, {"format": fmt}, 200)

    def export_payload(self, preview):
        return {
            "format": preview["preview_format"],
            "expected_version": preview["draft"]["version"],
            "expected_revision_hash": preview["draft"]["revision_hash"],
            "preview_sha256": preview["preview_sha256"],
        }

    def assert_error(self, method, path, token, body, status, code):
        actual, _, raw = self.request(method, path, token, body)
        self.assertEqual(actual, status, raw)
        self.assertEqual(json.loads(raw)["code"], code)

    def ledger_snapshot(self):
        tables = ("offerings", "purchases", "sales", "sale_lines", "stock_movements",
                  "cash_movements", "inventory_batches", "inventory_pools")
        with db_transaction(self.db_path) as conn:
            return {table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")]
                    for table in tables}

    def test_licensed_preview_and_export_match_for_each_format_without_publish_or_ledger_changes(self):
        ledger = self.ledger_snapshot()
        for fmt in ("svg", "png"):
            with self.subTest(format=fmt):
                preview = self.preview(fmt)
                self.assertEqual(preview["asset"]["asset_license"], "CC0-1.0")
                self.assertIn("MarketStudio Synthetic Sample Asset", preview["asset"]["attribution_text"])
                self.assertEqual(preview["asset"]["asset_source"], "marketstudio_local_sample")
                status, headers, content = self.request("POST", self.path + "/export", self.owner,
                                                        self.export_payload(preview))
                self.assertEqual(status, 200, content[:300])
                self.assertEqual(content, base64.b64decode(preview["preview_data_url"].split(",", 1)[1]))
                self.assertEqual(hashlib.sha256(content).hexdigest(), headers["X-Export-Sha256"])
                self.assertEqual(headers["X-Draft-Version"], str(self.draft["version"]))
                self.assertEqual(headers["X-Draft-Status"], "draft")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertTrue(headers["Content-Disposition"].endswith(f'.{fmt}"'))
                if fmt == "svg":
                    root = ElementTree.fromstring(content)
                    metadata = root.find(".//{https://marketstudio.local/ns/poster}poster")
                    self.assertEqual(metadata.attrib["asset_license"], "CC0-1.0")
                    self.assertEqual(metadata.attrib["version"], str(self.draft["version"]))
                else:
                    self.assertEqual(decode_png_rgb(content)[:2], (640, 800))
                    self.assertIn(b"AssetLicense\x00CC0-1.0", content)
        self.assertEqual(self.ledger_snapshot(), ledger)
        persisted = self.item("GET", self.path, self.owner, None, 200)
        self.assertEqual(persisted["status"], "draft")
        self.assertFalse(persisted["published"])
        with db_transaction(self.db_path) as conn:
            actions = [row["action"] for row in conn.execute(
                "SELECT action FROM audit_events WHERE entity_id = ? ORDER BY rowid", (self.draft["draft_id"],)
            )]
        self.assertEqual(actions, ["poster_draft.created", "poster_draft.previewed", "poster_draft.exported",
                                   "poster_draft.previewed", "poster_draft.exported"])

    def test_stale_version_format_and_changed_render_are_rejected(self):
        preview = self.preview()
        export = self.export_payload(preview)
        self.assert_error("POST", self.path + "/export", self.owner, {**export, "format": "png"},
                          409, "preview_required")
        with db_transaction(self.db_path, immediate=True) as conn:
            conn.execute("UPDATE workspaces SET name = ? WHERE workspace_id = ?", ("Nama usaha baru", self.ws_id))
        self.assert_error("POST", self.path + "/export", self.owner, export, 409, "preview_content_changed")
        newer_preview = self.preview()
        self.assertNotEqual(preview["preview_sha256"], newer_preview["preview_sha256"])
        self.assert_error("POST", self.path + "/export", self.owner, export, 409, "preview_content_changed")
        changed = self.item("PATCH", self.path, self.owner, {"headline": "Judul versi kedua"}, 200)
        self.assertEqual(changed["version"], self.draft["version"] + 1)
        self.assert_error("POST", self.path + "/export", self.owner, export, 409, "draft_version_conflict")
        self.assert_error("POST", self.path + "/export", self.owner,
                          {**export, "expected_version": changed["version"],
                           "expected_revision_hash": changed["revision_hash"]}, 409, "preview_required")

    def test_asset_failure_rejects_preview_and_export(self):
        preview = self.preview()
        export = self.export_payload(preview)
        asset_file = self.assets / "bakso-bowl-sample.png"
        asset_file.unlink()
        for method, payload in (("preview", {}), ("export", export)):
            self.assert_error("POST", f"{self.path}/{method}", self.owner, payload, 503, "asset_load_failed")
        asset_file.write_bytes(b"broken PNG")
        self.assert_error("POST", self.path + "/preview", self.owner, {}, 503, "asset_load_failed")
        shutil.copyfile(self.assets / "beras-harvest-sample.png", asset_file)
        self.assert_error("POST", self.path + "/preview", self.owner, {}, 503, "asset_load_failed")
        self.assert_error("POST", self.path + "/preview", self.owner, {"simulate_asset_failure": "unlicensed"},
                          422, "unlicensed_asset")

    def test_workspace_and_draft_access_precede_body_decoding(self):
        routes = [
            ("GET", self.root + "/creative-assets"), ("GET", self.root + "/creative-drafts"),
            ("GET", self.path), ("POST", self.root + "/creative-drafts"),
            ("POST", self.root + "/creative-drafts/sample"), ("PATCH", self.path),
            ("POST", self.path + "/preview"), ("POST", self.path + "/export"),
        ]
        for method, path in routes:
            with self.subTest(method=method, path=path):
                body = None if method == "GET" else b"{"
                self.assert_error(method, path, None, body, 401, "unauthenticated")
                self.assert_error(method, path, self.other, body, 404, "workspace_not_found")
        other_ws = self.item("POST", "/v1/workspaces", self.other, {"name": "Usaha lain"}, 201)
        cross_draft = f"/v1/workspaces/{other_ws['workspace_id']}/creative-drafts/{self.draft['draft_id']}"
        self.assert_error("POST", cross_draft + "/preview", self.other, b"{", 404, "poster_draft_not_found")
        self.assert_error("POST", self.path + "/preview", self.owner, b"{", 422, "invalid_json")

    def test_unavailable_backend_preserves_access_checks(self):
        # Keep the local connection and exercise the guard used by PostgreSQL mode.
        self.service.backend = "postgres"
        path = self.root + "/creative-assets"
        self.assert_error("GET", path, None, None, 401, "unauthenticated")
        self.assert_error("GET", path, self.other, None, 404, "workspace_not_found")
        self.assert_error("GET", path, self.owner, None, 503, "poster_backend_unavailable")
