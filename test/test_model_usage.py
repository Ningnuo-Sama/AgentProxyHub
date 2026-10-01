import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import model_usage


class ModelUsageTests(unittest.TestCase):
    def test_response_usage_is_redacted_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(model_usage, "DATA_DIR", Path(tmp)), patch.object(model_usage, "USAGE_FILE", Path(tmp) / "usage.jsonl"):
                result = model_usage.record_response_usage("glm", "glm-5.3-flash", {
                    "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
                    "choices": [{"message": {"content": "secret prompt and answer"}}],
                }, request_id="private-request")
                self.assertEqual(result["row"]["total_tokens"], 10)
                raw = (Path(tmp) / "usage.jsonl").read_text(encoding="utf-8")
                self.assertNotIn("secret prompt", raw)
                self.assertNotIn("private-request", raw)
                self.assertIn("request_id_hash", raw)

    def test_tracked_call_records_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(model_usage, "DATA_DIR", Path(tmp)), patch.object(model_usage, "USAGE_FILE", Path(tmp) / "usage.jsonl"):
                @model_usage.tracked_call("gemini", "gemini-3.8-flash-tiered")
                def broken():
                    raise RuntimeError("upstream failure")
                with self.assertRaises(RuntimeError):
                    broken()
                summary = model_usage.usage_summary()
                self.assertEqual(summary["count"], 1)
                self.assertEqual(summary["by_model"]["gemini/gemini-3.8-flash-tiered"]["requests"], 1)


if __name__ == "__main__":
    unittest.main()
