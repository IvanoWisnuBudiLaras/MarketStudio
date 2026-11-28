"""Creative Studio generated image contract, state transitions and tenant boundaries."""

import base64
import hashlib
import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

from app.ai_image import HttpsImageProvider, StubImageProvider, configured_provider, normalize_image
from app.creative import encode_png_rgb
from app.db import init_db
from app.domain import DomainError
from app.service import BaselineService


class AIImageTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db = str(Path(directory) / "test.db")
        init_db(self.db)
        self.service = BaselineService(self.db)
        self.actor = "actor_a"
        self.workspace = self.service.bootstrap_demo_workspace(self.actor)[1]["workspace"]["workspace_id"]
        self.offering = self.service.list_offerings(self.workspace, self.actor)[0]["offering_id"]
        self.brief = {"offering_id": self.offering, "style": "studio"}

    def assets(self):
        return self.service.list_creative_assets(self.workspace, self.actor)

    def generate(self, asset_id, provider, brief=None):
        return self.service.generate_creative_image(
            self.workspace, self.actor, asset_id, self.brief if brief is None else brief, provider=provider,
        )

    def test_ready_asset_renders_exact_preview_with_internal_provenance(self):
        asset_id = "img_" + uuid.uuid4().hex
        provider = StubImageProvider("valid")
        seen = []
        original = provider.generate

        def record_prompt(prompt):
            seen.append(prompt)
            return original(prompt)

        provider.generate = record_prompt
        item = self.generate(asset_id, provider)
        provenance = item["asset_provenance"]
        self.assertEqual(seen, [provenance["prompt"]])
        self.assertNotIn(self.offering, seen[0])
        self.assertNotIn("Bakso", seen[0])
        self.assertEqual(provenance["provider"], "stub_test")
        self.assertEqual(item["asset_license"], "internal_use_only")
        png = base64.b64decode(item["preview_data_url"].split(",", 1)[1])
        self.assertEqual(hashlib.sha256(png).hexdigest(), provenance["sha256"])
        self.assertNotIn("png", self.assets()[-1])
        self.assertNotIn("preview_data_url", self.assets()[-1])

        status, draft = self.service.create_sample_poster_draft(self.workspace, self.actor, "sample")
        self.assertEqual(status, 201)
        draft_id = draft["draft_id"]
        chosen = self.service.update_poster_draft(self.workspace, draft_id, self.actor, {
            "asset_id": asset_id, "expected_version": draft["version"],
        })
        self.assertEqual(chosen["version"], draft["version"] + 1)
        self.assertEqual(chosen["asset_provenance"]["prompt"], seen[0])
        for fmt in ("png", "svg"):
            with self.subTest(fmt=fmt):
                preview = self.service.preview_poster_draft(self.workspace, draft_id, self.actor, {"format": fmt})
                result = self.service.export_poster_draft(self.workspace, draft_id, self.actor, {
                    "format": fmt, "expected_version": chosen["version"], "preview_sha256": preview["preview_sha256"],
                })
                self.assertEqual(result["content_bytes"], base64.b64decode(preview["preview_data_url"].split(",", 1)[1]))
        with self.assertRaises(DomainError) as rejected:
            self.service.preview_catalog(self.workspace, self.actor, {"offering_ids": [self.offering], "asset_id": asset_id})
        self.assertEqual(rejected.exception.code, "asset_internal_only")

    def test_reject_unverified_output_and_retry_with_new_id(self):
        asset_id = "img_" + uuid.uuid4().hex
        for mode, code in (("timeout", "image_provider_timeout"), ("failure", "image_provider_failed")):
            with self.subTest(mode=mode):
                with self.assertRaises(DomainError) as failed:
                    self.generate("img_" + uuid.uuid4().hex, StubImageProvider(mode))
                self.assertEqual(failed.exception.code, code)
        provider = StubImageProvider("valid")
        provider.generate = lambda prompt: b"not a PNG"
        with self.assertRaises(DomainError) as invalid:
            self.generate(asset_id, provider)
        self.assertEqual(invalid.exception.code, "image_output_invalid")
        with self.assertRaises(DomainError) as duplicate:
            self.generate(asset_id, StubImageProvider("valid"))
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertTrue(all(asset["is_builtin"] for asset in self.assets()))
        self.generate("img_" + uuid.uuid4().hex, StubImageProvider("valid"))
        self.assertEqual(self.assets()[-1]["asset_source"], "ai_generated")

    def test_cancel_in_flight_discards_late_result_and_cannot_be_replayed(self):
        started, release = Event(), Event()
        asset_id = "img_" + uuid.uuid4().hex
        provider = StubImageProvider("valid")
        original = provider.generate

        def delayed(prompt):
            started.set()
            if not release.wait(5):
                raise TimeoutError
            return original(prompt)

        provider.generate = delayed
        with ThreadPoolExecutor(1) as worker:
            pending = worker.submit(self.generate, asset_id, provider)
            try:
                self.assertTrue(started.wait(5))
                with self.assertRaises(DomainError) as outsider:
                    self.service.cancel_creative_image(self.workspace, "actor_b", asset_id)
                self.assertEqual(outsider.exception.status_code, 404)
                self.service.cancel_creative_image(self.workspace, self.actor, asset_id)
            finally:
                release.set()
            with self.assertRaises(DomainError) as stopped:
                pending.result(timeout=5)
        self.assertEqual(stopped.exception.code, "image_cancelled")
        with self.assertRaises(DomainError) as duplicate:
            self.generate(asset_id, provider)
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertTrue(all(asset["is_builtin"] for asset in self.assets()))

    def test_output_size_aspect_and_configuration(self):
        for width, height in ((600, 399), (400, 400), (1900, 1060)):
            with self.subTest(size=(width, height)), self.assertRaises(DomainError):
                normalize_image(encode_png_rgb(width, height, bytes(width * height * 3)))
        with patch.dict(os.environ, {"MARKETSTUDIO_AI_IMAGE_STUB": "valid"}, clear=True):
            with self.assertRaises(DomainError) as disabled:
                configured_provider()
            self.assertEqual(disabled.exception.code, "image_provider_unavailable")

    def test_validation_conflict_and_backend_guard(self):
        asset_id = "img_" + uuid.uuid4().hex
        provider = StubImageProvider("valid")
        for bad_payload in (
            {},
            {"offering_id": self.offering},
            {"offering_id": self.offering, "style": "unknown_style"},
            {"offering_id": "nonexistent_offering", "style": "studio"},
            {"offering_id": self.offering, "style": "studio", "extra": "field"},
        ):
            with self.subTest(payload=bad_payload), self.assertRaises(DomainError) as err:
                self.generate(asset_id, provider, brief=bad_payload)
            self.assertIn(err.exception.status_code, (404, 422))

        self.generate(asset_id, provider)

        with self.assertRaises(DomainError) as cancel_conflict:
            self.service.cancel_creative_image(self.workspace, self.actor, asset_id)
        self.assertEqual(cancel_conflict.exception.status_code, 409)
        self.assertEqual(cancel_conflict.exception.code, "image_cancel_conflict")

        self.service.backend = "postgres"
        with self.assertRaises(DomainError) as unavail:
            self.service.require_poster_access(self.workspace, self.actor)
        self.assertEqual(unavail.exception.status_code, 503)
        self.assertEqual(unavail.exception.code, "poster_backend_unavailable")

    def test_https_image_provider_configuration_and_mock_gateway(self):
        env_valid = {
            "MARKETSTUDIO_AI_IMAGE_APPROVED": "1",
            "MARKETSTUDIO_AI_IMAGE_URL": "https://gateway.example.com/v1/generate",
            "MARKETSTUDIO_AI_IMAGE_TOKEN": "secret-bearer-token-12345",
        }
        with patch.dict(os.environ, env_valid, clear=True):
            prov = configured_provider()
            self.assertIsInstance(prov, HttpsImageProvider)
            self.assertEqual(prov.name, "approved_https_gateway")
            self.assertNotIn("secret-bearer-token-12345", repr(prov))

        for bad_env in (
            {**env_valid, "MARKETSTUDIO_AI_IMAGE_APPROVED": "0"},
            {**env_valid, "MARKETSTUDIO_AI_IMAGE_URL": "http://insecure.example.com/v1/generate"},
            {**env_valid, "MARKETSTUDIO_AI_IMAGE_URL": "https://user:pass@gateway.example.com/v1/generate"},
            {**env_valid, "MARKETSTUDIO_AI_IMAGE_URL": "https://gateway.example.com/v1/generate?param=val"},
            {**env_valid, "MARKETSTUDIO_AI_IMAGE_URL": "https://gateway.example.com/v1/generate#frag"},
            {**env_valid, "MARKETSTUDIO_AI_IMAGE_TOKEN": ""},
        ):
            with self.subTest(env=bad_env), patch.dict(os.environ, bad_env, clear=True):
                with self.assertRaises(DomainError) as err:
                    configured_provider()
                self.assertEqual(err.exception.code, "image_provider_unavailable")

        https_prov = HttpsImageProvider(env_valid["MARKETSTUDIO_AI_IMAGE_URL"], env_valid["MARKETSTUDIO_AI_IMAGE_TOKEN"])
        stub_png = StubImageProvider("valid").generate("test prompt")

        class MockResponse:
            def __init__(self, data: bytes, content_type: str = "image/png"):
                self.data = data
                self.headers = MagicMock()
                self.headers.get_content_type.return_value = content_type
                self.read_pos = 0

            def read1(self, size: int) -> bytes:
                chunk = self.data[self.read_pos : self.read_pos + size]
                self.read_pos += len(chunk)
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch("urllib.request.build_opener") as mock_opener:
            mock_opener.return_value.open.return_value = MockResponse(stub_png)
            output = https_prov.generate("test prompt")
            self.assertEqual(output, stub_png)

            mock_opener.return_value.open.return_value = MockResponse(b"{}", content_type="application/json")
            with self.assertRaises(DomainError) as invalid_ct:
                https_prov.generate("test prompt")
            self.assertEqual(invalid_ct.exception.code, "image_output_invalid")

            mock_opener.return_value.open.side_effect = OSError("connection reset")
            with self.assertRaises(DomainError) as net_err:
                https_prov.generate("test prompt")
            self.assertEqual(net_err.exception.code, "image_provider_failed")
            self.assertNotIn("secret-bearer-token-12345", str(net_err.exception))
