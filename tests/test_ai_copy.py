"""Grounding, persistence and failure boundaries for Creative Studio copy."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ai_copy import generate_copy
from app.db import init_db
from app.domain import DomainError
from app.service import BaselineService


class CreativeCopyTest(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        db_path = str(Path(temp) / "copy.sqlite3")
        init_db(db_path)
        self.service = BaselineService(db_path)
        self.actor = "actor_a"
        _, ws = self.service.create_workspace({"name": "Katering Sintetis"}, actor=self.actor)
        self.workspace = ws["workspace_id"]
        _, self.offering = self.service.create_offering(self.workspace, self.actor, {
            "name": "Kelas Keramik",
            "offering_type": "service",
            "description": "Peserta membentuk mangkuk dari tanah liat.",
            "unit_price_idr": 125000,
            "unit": "sesi",
        })
        self.payload = {
            "offering_id": self.offering["offering_id"],
            "asset_id": "asset_bakso_bowl_v1",
            "tone": "direct",
            "unit_price_idr": 1,
            "description": "Diskon 99%",
        }

    def create(self, payload=None, key="test-copy"):
        return self.service.create_caption_draft(
            self.workspace, self.actor, payload or self.payload, key,
        )[1]

    @patch.dict(os.environ, {"MARKETSTUDIO_ENV": "development", "MARKETSTUDIO_AI_COPY_STUB": "stub_valid"})
    def test_source_of_truth_idempotency_partial_edit_and_catalog_snapshot(self):
        draft = self.create()
        self.assertEqual(draft, self.create())
        self.assertIn("Rp 125.000 / sesi", draft["caption"])
        self.assertIn(self.offering["description"], draft["caption"])
        self.assertIn("Jasa", draft["caption"])
        self.assertNotIn("Diskon", draft["caption"])
        self.assertEqual(draft["copy_provenance"]["provider_mode"], "stub_test")
        self.assertEqual(draft["copy_provenance"]["tone"], "direct")
        draft_id = draft["draft_id"]
        edited = self.service.update_poster_draft(self.workspace, draft_id, self.actor, {
            "caption": "Edisi pemilik <b>sintetis</b>",
            "expected_version": draft["version"],
        })
        self.assertEqual(edited["headline"], draft["headline"])
        self.assertEqual(edited["price_label"], draft["price_label"])
        self.assertEqual(edited["copy_provenance"]["generated_at"], draft["copy_provenance"]["generated_at"])
        self.assertEqual(edited["copy_provenance"]["last_copy_edit_version"], edited["version"])
        self.assertEqual(edited, self.service.get_poster_draft(self.workspace, draft_id, self.actor))
        selection = {
            "offering_ids": [self.offering["offering_id"]],
            "copy_draft": {"draft_id": draft_id, "version": draft["version"]},
        }
        with self.assertRaises(DomainError) as stale:
            self.service.preview_catalog(self.workspace, self.actor, selection)
        self.assertEqual(stale.exception.status_code, 409)
        selection["copy_draft"]["version"] = edited["version"]
        catalog = self.service.preview_catalog(self.workspace, self.actor, selection)
        self.assertIsNone(catalog["public_path"])
        self.assertIn("Edisi pemilik &lt;b&gt;sintetis&lt;/b&gt;", catalog["draft"]["html"])

    @patch.dict(os.environ, {"MARKETSTUDIO_ENV": "development", "MARKETSTUDIO_AI_COPY_STUB": "stub_timeout"})
    def test_failure_has_no_side_effect_manual_and_foreign_offering(self):
        with self.assertRaises(DomainError) as timeout:
            self.create()
        self.assertEqual(timeout.exception.code, "provider_timeout")
        self.assertEqual(self.service.list_poster_drafts(self.workspace, self.actor), [])
        manual = self.create({**self.payload, "mode": "manual"})
        self.assertEqual(manual["caption"], "")
        self.assertEqual(manual["copy_source"], "manual")
        _, other = self.service.create_workspace({"name": "Usaha lain"}, actor="actor_b")
        with self.assertRaises(DomainError) as denied:
            self.service.create_caption_draft(other["workspace_id"], "actor_b", self.payload, None)
        self.assertEqual(denied.exception.code, "offering_not_found")

    @patch.dict(os.environ, {"MARKETSTUDIO_ENV": "production", "MARKETSTUDIO_AI_COPY_STUB": "stub_valid"})
    @patch("app.ai_copy.get_ai_provider_config_status", return_value={"configured": True, "model": "test-model"})
    @patch("app.ai_copy.call_gemini_json", return_value=({"opening": "Diskon 90%", "closing": "details"}, None))
    def test_provider_cannot_add_claims_or_receive_offering_text(self, provider, _config):
        with self.assertRaises(DomainError) as rejected:
            generate_copy(self.offering, "direct")
        self.assertEqual(rejected.exception.code, "invalid_provider_output")
        prompt = provider.call_args.args[0]
        for field in ("name", "description", "unit_price_idr", "offering_id"):
            self.assertNotIn(str(self.offering[field]), prompt)
