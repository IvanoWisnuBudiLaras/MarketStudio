"""Contract & provider access tests for Issue #40."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.ai_review import build_metric_snapshot
from app.db import init_db
from app.service import BaselineService


class AIContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "ai_contract_40.sqlite3")
        init_db(self.db_path)
        self.service = BaselineService(db_path=self.db_path)
        self.owner = "owner_40"
        _, self.ws = self.service.create_workspace(
            {"name": "Toko Rahasia #40", "timezone": "Asia/Jakarta"},
            actor=self.owner,
        )
        self.ws_id = self.ws["workspace_id"]

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_config_check_never_exposes_secret_values(self) -> None:
        secret = "AIzaSy_SECRET_40_DO_NOT_LEAK"
        with mock.patch.dict(
            os.environ,
            {
                "MARKETSTUDIO_AI_PROVIDER": "gemini",
                "MARKETSTUDIO_AI_MODEL": "gemini-2.5-flash",
                "GEMINI_API_KEY": secret,
            },
            clear=False,
        ):
            cfg = self.service.get_ai_review_config(self.ws_id, self.owner)
            self.assertTrue(cfg["configured"])
            self.assertNotIn(secret, json.dumps(cfg))

    def test_metric_snapshot_minimizes_outbound_payload(self) -> None:
        report = self.service.get_daily_report(self.ws_id, self.owner)
        snap = build_metric_snapshot(report)
        outbound = json.dumps(snap["outbound_payload"])
        self.assertNotIn("Toko Rahasia #40", outbound)
        self.assertNotIn(self.ws_id, outbound)
        self.assertNotIn(self.owner, outbound)
        self.assertIn("IDR", outbound)


if __name__ == "__main__":
    unittest.main()
