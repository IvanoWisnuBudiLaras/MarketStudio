"""Unit and integration tests for the MarketStudio stack spike benchmark script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.spike_stack_metrics import run_spike


class StackSpikeMetricsTest(unittest.TestCase):
    """Test suite for scripts/spike_stack_metrics.py."""

    def test_run_spike_library_call(self) -> None:
        """Verify direct library execution returns valid metrics across alur #1."""
        res = run_spike(iterations=1, quiet=True)

        self.assertIn("timestamp_utc", res)
        self.assertIn("startup_inprocess_ms", res)
        self.assertGreater(res["startup_inprocess_ms"], 0.0)
        self.assertIn("cold_startup_ms", res)
        self.assertGreater(res["cold_startup_ms"], 0.0)
        self.assertIn("idle_rss_mb", res)
        self.assertGreater(res["idle_rss_mb"], 0.0)
        self.assertIn("loaded_rss_mb", res)
        self.assertGreater(res["loaded_rss_mb"], 0.0)
        self.assertIn("database_size_kb", res)
        self.assertGreater(res["database_size_kb"], 0.0)

        step_keys = {
            "post_sessions",
            "post_workspaces",
            "post_offerings_goods",
            "post_offerings_service",
            "post_purchases",
            "post_sales",
            "get_daily_report",
        }
        self.assertEqual(set(res["step_latencies_ms"].keys()), step_keys)
        for step, metrics in res["step_latencies_ms"].items():
            self.assertIn("mean_ms", metrics, f"Missing mean_ms in step {step}")
            self.assertIn("min_ms", metrics, f"Missing min_ms in step {step}")
            self.assertIn("max_ms", metrics, f"Missing max_ms in step {step}")
            self.assertGreaterEqual(metrics["min_ms"], 0.0)
            self.assertGreaterEqual(metrics["max_ms"], metrics["min_ms"])

        summary = res["summary"]
        self.assertIn("total_flow_latency_mean_ms", summary)
        self.assertGreater(summary["total_flow_latency_mean_ms"], 0.0)

    def test_run_spike_invalid_iterations(self) -> None:
        """Verify invalid iterations parameter raises ValueError."""
        with self.assertRaises(ValueError):
            run_spike(iterations=0)

    def test_cli_json_mode(self) -> None:
        """Verify CLI execution with --json outputs valid parseable JSON."""
        script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "spike_stack_metrics.py")
        proc = subprocess.run(
            [sys.executable, script_path, "--iterations", "1", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"CLI failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertEqual(data["database_backend"], "sqlite")
        self.assertEqual(data["iterations"], 1)
        self.assertIn("total_flow_latency_mean_ms", data["summary"])

    def test_cli_quiet_and_custom_db_path(self) -> None:
        """Verify CLI execution with custom new --db-path and quiet flag creates file."""
        script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "spike_stack_metrics.py")
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_db = Path(tmpdir) / "new_custom_spike.db"
            proc = subprocess.run(
                [
                    sys.executable,
                    script_path,
                    "--db-path",
                    str(custom_db),
                    "--iterations",
                    "1",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, f"CLI failed: {proc.stderr}")
            self.assertEqual(proc.stdout.strip(), "")
            self.assertTrue(custom_db.is_file())
            self.assertGreater(custom_db.stat().st_size, 0)

    def test_cli_rejects_existing_db_path(self) -> None:
        """Verify CLI execution rejects existing database file with non-zero exit code without mutating it."""
        script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "spike_stack_metrics.py")
        with tempfile.NamedTemporaryFile(suffix=".db") as existing_file:
            existing_path = Path(existing_file.name)
            original_size = existing_path.stat().st_size

            proc = subprocess.run(
                [
                    sys.executable,
                    script_path,
                    "--db-path",
                    str(existing_path),
                    "--iterations",
                    "1",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("sudah ada", proc.stderr)
            self.assertIn("hanya menerima path file baru", proc.stderr)
            self.assertEqual(existing_path.stat().st_size, original_size)

    def test_run_spike_library_rejects_existing_db_path(self) -> None:
        """Verify library execution raises ValueError when target db file already exists."""
        with tempfile.NamedTemporaryFile(suffix=".db") as existing_file:
            with self.assertRaises(ValueError) as ctx:
                run_spike(db_path=existing_file.name, iterations=1, quiet=True)
            self.assertIn("sudah ada", str(ctx.exception))

    def test_spike_backend_isolation_with_postgres_env(self) -> None:
        """Verify spike strictly isolates SQLite backend even when PostgreSQL environment variables are configured."""
        script_path = str(Path(__file__).resolve().parents[1] / "scripts" / "spike_stack_metrics.py")
        env = dict(
            os.environ,
            MARKETSTUDIO_DB_BACKEND="postgres",
            DATABASE_URL="postgresql://unreachable_user:dummy@127.0.0.1:5432/unreachable_db",
            MARKETSTUDIO_DATABASE_URL="postgresql://unreachable_user:dummy@127.0.0.1:5432/unreachable_db",
        )
        proc = subprocess.run(
            [sys.executable, script_path, "--iterations", "1", "--json"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"Spike should isolate to SQLite despite PG env: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertEqual(data["database_backend"], "sqlite")
        self.assertIn("total_flow_latency_mean_ms", data["summary"])


if __name__ == "__main__":
    unittest.main()
