"""Deterministic fallback tests for Issue #41."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.ai_review import execute_ai_review
from app.db import init_db
from app.service import BaselineService


class AIFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "ai_fallback_41.sqlite3")
        init_db(self.db_path)
        self.service = BaselineService(db_path=self.db_path)
        self.owner = "owner_41"
        _, self.ws = self.service.create_workspace(
            {"name": "Warung #41", "timezone": "Asia/Jakarta"},
            actor=self.owner,
        )
        self.ws_id = self.ws["workspace_id"]

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_fallback_on_unconfigured_timeout_error_empty_and_invalid(self) -> None:
        report = self.service.get_daily_report(self.ws_id, self.owner)
        with mock.patch.dict(os.environ, {}, clear=True):
            res_unconf = execute_ai_review(report)
            self.assertEqual(res_unconf["status"], "fallback")
            self.assertEqual(res_unconf["provider_mode"], "deterministic_fallback")
            self.assertEqual(res_unconf["fallback_reason"], "provider_unconfigured")
            self.assertIn("Ringkasan deterministik", res_unconf["review"]["summary"])

        for stub_mode, expected_reason in (
            ("stub_timeout", "provider_timeout"),
            ("stub_error", "provider_error"),
            ("stub_empty", "empty_response"),
            ("stub_fake_citation", "fake_citation"),
            ("stub_wrong_period", "period_mismatch"),
        ):
            res = execute_ai_review(report, stub_mode=stub_mode)
            self.assertEqual(res["status"], "fallback", msg=stub_mode)
            self.assertEqual(res["provider_mode"], "deterministic_fallback", msg=stub_mode)
            self.assertEqual(res["fallback_reason"], expected_reason, msg=stub_mode)
            self.assertIn("Ringkasan deterministik", res["review"]["summary"])


if __name__ == "__main__":
    unittest.main()
