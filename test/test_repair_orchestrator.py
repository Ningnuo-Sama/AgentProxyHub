import tempfile
import unittest
from pathlib import Path

from core.repair_orchestrator import RepairOrchestrator, RepairPlan, repair_id, should_auto_repair


class RepairOrchestratorTests(unittest.TestCase):
    def make_plan(self, **changes):
        data = {
            "repair_id": repair_id("test", "bug-1"),
            "scope": "test",
            "symptom": "test failure",
            "root_cause": "deterministic defect",
            "candidate": "isolated patch",
            "tests": ("unit",),
        }
        data.update(changes)
        return RepairPlan(**data)

    def test_safe_plan_is_auto_repair_candidate(self):
        plan = self.make_plan()
        self.assertTrue(plan.validate()["ok"])
        self.assertTrue(should_auto_repair(plan))

    def test_sensitive_plan_is_blocked(self):
        plan = self.make_plan(risks=("production_deploy",))
        self.assertFalse(plan.validate()["ok"])
        self.assertFalse(should_auto_repair(plan))
        self.assertIn("manual_gate:production_deploy", plan.validate()["errors"])

    def test_record_is_atomic_and_redacted_to_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "repair_state.json"
            events = Path(folder) / "events.jsonl"
            from core.autonomy_core import EventStore
            row = RepairOrchestrator(state, EventStore(events)).record(self.make_plan())
            self.assertTrue(row["validation"]["ok"])
            self.assertTrue(state.exists())
            self.assertNotIn("cookie", state.read_text(encoding="utf-8").lower())
            self.assertTrue(events.exists())


if __name__ == "__main__":
    unittest.main()
