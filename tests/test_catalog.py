"""Acceptance checks for the catalog's anonymous and owner boundaries."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.db import db_transaction
from app.server import create_server


class CatalogTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db_path = str(Path(directory) / "catalog.sqlite3")
        server = create_server(port=0, db_path=self.db_path)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"
        self.owner = self.login("actor_a", "dev-a-pass")
        self.other = self.login("actor_b", "dev-b-pass")
        self.workspace, self.offering, self.unselected = self.demo(self.owner)
        self.other_workspace, self.other_offering, _ = self.demo(self.other)
        self.path = f"/v1/workspaces/{self.workspace}/catalog"

    def request(self, method, path, status, token=None, payload=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            self.assertEqual(response.status, status, raw[:300])
            return response.headers, raw

    def item(self, method, path, status, token=None, payload=None):
        _, raw = self.request(method, path, status, token, payload)
        return json.loads(raw)["item"]

    def login(self, actor, passcode):
        return self.item("POST", "/v1/sessions", 201, payload={"actor_id": actor, "passcode": passcode})["token"]

    def demo(self, token):
        demo = self.item("POST", "/v1/workspaces/demo", 201, token, {})
        workspace = demo["workspace"]["workspace_id"]
        _, raw = self.request("GET", f"/v1/workspaces/{workspace}/offerings", 200, token)
        first, second, *_ = json.loads(raw)["items"]
        return workspace, first, second

    def stage(self, asset=None):
        state = self.item("POST", self.path + "/preview", 200, self.owner, {
            "offering_ids": [self.offering["offering_id"]], "asset_id": asset,
        })
        return state["draft"]

    def publish(self, draft, status=200):
        return self.item("POST", self.path + "/publish", status, self.owner, {
            "version_id": draft["version_id"],
        })["public_path"]

    def test_exact_snapshot_republication_and_revocation(self):
        original = self.stage("asset_bakso_bowl_v1")
        self.assertIsNone(self.item("GET", self.path, 200, self.owner)["public_path"])
        self.request("GET", f'/katalog/{original["version_id"]}', 404)
        with db_transaction(self.db_path, immediate=True) as conn:
            conn.execute("UPDATE offerings SET name = ?, unit_price_idr = ? WHERE offering_id = ?",
                         ("<script>Nama baru</script>", 432100, self.offering["offering_id"]))
        url = self.publish(original)
        self.assertEqual(url, self.publish(original))
        headers, raw = self.request("GET", url, 200)
        self.assertEqual(headers["Cache-Control"], "no-store, no-cache, must-revalidate")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(raw.decode(), original["html"])
        self.assertIn(self.offering["name"].encode(), raw)
        self.assertNotIn(self.unselected["name"].encode(), raw)
        for private in ("workspace_id", self.workspace, "offering_id", "cogs", "profit_margin", "ledger", "file_path"):
            self.assertNotIn(private.encode(), raw)
        self.assertIn(b"data:image/png;base64,", raw)
        self.assertNotIn(b"asset_bakso_bowl_v1", raw)
        self.request("HEAD", url, 200)

        obsolete = self.stage()
        current = self.stage()
        self.request("POST", self.path + "/publish", 409, self.owner, {"version_id": obsolete["version_id"]})
        self.assertEqual(self.request("GET", url, 200)[1], raw)
        new_url = self.publish(current)
        self.assertNotEqual(url, new_url)
        self.assertEqual(self.request("GET", url, 404)[0]["Cache-Control"],
                         "no-store, no-cache, must-revalidate")
        new_raw = self.request("GET", new_url, 200)[1]
        self.assertIn(b"&lt;script&gt;Nama baru&lt;/script&gt;", new_raw)
        self.assertIn(b"432.100", new_raw)
        self.assertNotIn(b"data:image/png;base64,", new_raw)

        for version_url in (url, new_url, new_url):
            state = self.item("POST", self.path + "/unpublish", 200, self.owner, {
                "token": version_url.split("/")[-1],
            })
            self.assertEqual(state["public_path"], new_url if version_url == url else None)
        self.assertEqual(self.request("HEAD", new_url, 404)[0]["Cache-Control"],
                         "no-store, no-cache, must-revalidate")
        self.request("POST", self.path + "/publish", 409, self.owner, {"version_id": current["version_id"]})

    def test_tenant_and_owner_checks(self):
        draft = self.stage()
        for token, status in ((None, 401), (self.other, 404)):
            self.request("GET", self.path, status, token)
            self.request("POST", self.path + "/preview", status, token, {"offering_ids": []})
            self.request("POST", self.path + "/publish", status, token, {"version_id": draft["version_id"]})
            self.request("POST", self.path + "/unpublish", status, token, {"token": "private"})
        self.request("POST", self.path + "/preview", 404, self.owner, {
            "offering_ids": [self.other_offering["offering_id"]],
        })
        self.request("POST", self.path + "/preview", 404, self.owner, {
            "offering_ids": [self.offering["offering_id"]], "asset_id": "unknown",
        })
        url = self.publish(draft)
        foreign = f"/v1/workspaces/{self.other_workspace}/catalog"
        self.request("POST", foreign + "/publish", 409, self.other, {"version_id": draft["version_id"]})
        self.request("POST", foreign + "/unpublish", 404, self.other, {"token": url.split("/")[-1]})
        self.request("GET", url, 200)
        with db_transaction(self.db_path, immediate=True) as conn:
            conn.execute("UPDATE workspace_memberships SET role = 'member' WHERE workspace_id = ?", (self.workspace,))
        self.request("GET", self.path, 404, self.owner)
        self.request("POST", self.path + "/unpublish", 404, self.owner, {"token": url.split("/")[-1]})
