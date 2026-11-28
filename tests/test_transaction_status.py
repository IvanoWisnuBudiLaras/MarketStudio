"""Unit and contract tests for transaction status, idempotency, and retry behavior (Issue #7)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import init_db
from app.domain import DomainError
from app.service import BaselineService


class TransactionStatusIdempotencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_status.sqlite"
        init_db(self.db_path)
        self.service = BaselineService(self.db_path)
        self.actor = "synthetic_owner"
        _, ws = self.service.create_workspace({"name": "Toko Status Uji"}, actor=self.actor)
        self.ws_id = ws["workspace_id"]
        _, off = self.service.create_offering(
            self.ws_id,
            actor_id=self.actor,
            payload={
                "name": "Kopi Uji",
                "offering_type": "goods",
                "unit": "cup",
                "unit_price_idr": 15000,
            },
            actor=self.actor,
        )
        self.offering_id = off["offering_id"]
        # Stock initial purchase: 50 cups @ 5000
        self.service.create_purchase(
            self.ws_id,
            actor_id=self.actor,
            payload={
                "offering_id": self.offering_id,
                "qty": "50",
                "total_cost_idr": 250000,
            },
            idempotency_key="init-pur-1",
            actor=self.actor,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sale_idempotency_replay_prevents_duplicate_mutations(self) -> None:
        """When a sale request commits but response is lost, retry with the same key
        must return the existing transaction without duplicating stock or cash movements.
        """
        key = "sale-retry-key-001"
        payload = {
            "lines": [
                {
                    "offering_id": self.offering_id,
                    "qty": "2",
                    "total_price_idr": 30000,
                }
            ]
        }

        # 1. Initial attempt
        status1, res1 = self.service.create_sale(
            self.ws_id, actor_id=self.actor, payload=payload, idempotency_key=key, actor=self.actor
        )
        self.assertEqual(status1, 201)
        sale_id = res1["sale_id"]

        # 2. Replay attempt (simulate client retrying with same key after dropped connection)
        status2, res2 = self.service.create_sale(
            self.ws_id, actor_id=self.actor, payload=payload, idempotency_key=key, actor=self.actor
        )
        self.assertEqual(status2, 201)
        self.assertEqual(res2["sale_id"], sale_id)
        self.assertEqual(res2["total_revenue_idr"], 30000)

        # 3. Prove invariant: exactly 1 sale row, 1 stock movement, 1 cash movement in DB
        with self.service._tx() as conn:
            sale_count = conn.execute(
                "SELECT count(*) FROM sales WHERE workspace_id = ?", (self.ws_id,)
            ).fetchone()[0]
            self.assertEqual(sale_count, 1)

            stock_out_count = conn.execute(
                "SELECT count(*) FROM stock_movements WHERE workspace_id = ? AND movement_type = 'sale_out'",
                (self.ws_id,),
            ).fetchone()[0]
            self.assertEqual(stock_out_count, 1)

            cash_in_count = conn.execute(
                "SELECT count(*) FROM cash_movements WHERE workspace_id = ? AND direction = 'in'",
                (self.ws_id,),
            ).fetchone()[0]
            self.assertEqual(cash_in_count, 1)

    def test_purchase_idempotency_replay_prevents_duplicate_mutations(self) -> None:
        """When a purchase request commits but response is lost, retry with same key
        must replay without adding duplicate inventory or cash deduction.
        """
        key = "pur-retry-key-001"
        payload = {
            "offering_id": self.offering_id,
            "qty": "10",
            "total_cost_idr": 50000,
        }

        # Initial attempt
        status1, res1 = self.service.create_purchase(
            self.ws_id, actor_id=self.actor, payload=payload, idempotency_key=key, actor=self.actor
        )
        self.assertEqual(status1, 201)
        pur_id = res1["purchase_id"]

        # Replay attempt
        status2, res2 = self.service.create_purchase(
            self.ws_id, actor_id=self.actor, payload=payload, idempotency_key=key, actor=self.actor
        )
        self.assertEqual(status2, 201)
        self.assertEqual(res2["purchase_id"], pur_id)

        # Invariant: exactly 2 purchases in DB (1 init + 1 new)
        with self.service._tx() as conn:
            pur_count = conn.execute(
                "SELECT count(*) FROM purchases WHERE workspace_id = ?", (self.ws_id,)
            ).fetchone()[0]
            self.assertEqual(pur_count, 2)

    def test_idempotency_conflict_on_payload_change(self) -> None:
        """Modifying the payload while reusing the key must raise 409 idempotency_conflict."""
        key = "sale-conflict-key"
        payload_orig = {
            "lines": [{"offering_id": self.offering_id, "qty": "1", "total_price_idr": 15000}]
        }
        self.service.create_sale(
            self.ws_id, actor_id=self.actor, payload=payload_orig, idempotency_key=key, actor=self.actor
        )

        payload_modified = {
            "lines": [{"offering_id": self.offering_id, "qty": "2", "total_price_idr": 30000}]
        }
        with self.assertRaises(DomainError) as cm:
            self.service.create_sale(
                self.ws_id, actor_id=self.actor, payload=payload_modified, idempotency_key=key, actor=self.actor
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.code, "idempotency_conflict")

    def test_new_idempotency_key_records_distinct_transaction(self) -> None:
        """Generating a new idempotency key creates a separate transaction."""
        payload = {
            "lines": [{"offering_id": self.offering_id, "qty": "1", "total_price_idr": 15000}]
        }
        status1, res1 = self.service.create_sale(
            self.ws_id, actor_id=self.actor, payload=payload, idempotency_key="key-A", actor=self.actor
        )
        status2, res2 = self.service.create_sale(
            self.ws_id, actor_id=self.actor, payload=payload, idempotency_key="key-B", actor=self.actor
        )
        self.assertEqual(status1, 201)
        self.assertEqual(status2, 201)
        self.assertNotEqual(res1["sale_id"], res2["sale_id"])


if __name__ == "__main__":
    unittest.main()
