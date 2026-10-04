import json
import subprocess
import unittest

from core.alert_dispatch import _hermes_result


class AlertDispatchTests(unittest.TestCase):
    def test_hermes_requires_json_success(self):
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps({"success": True}), stderr="")
        sent, detail = _hermes_result(completed)
        self.assertTrue(sent)
        self.assertEqual(detail["status"], "sent")

    def test_hermes_error_is_not_reported_as_sent(self):
        completed = subprocess.CompletedProcess([], 1, stdout=json.dumps({"error": "session_not_ready"}), stderr="")
        sent, detail = _hermes_result(completed)
        self.assertFalse(sent)
        self.assertEqual(detail["status"], "failed")
        self.assertEqual(detail["error"], "session_not_ready")

    def test_empty_or_non_json_is_failed(self):
        completed = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        sent, detail = _hermes_result(completed)
        self.assertFalse(sent)
        self.assertEqual(detail["status"], "failed")


if __name__ == "__main__":
    unittest.main()
