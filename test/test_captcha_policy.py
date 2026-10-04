import unittest

from core.captcha_policy import decide


class CaptchaPolicyTests(unittest.TestCase):
    def base(self):
        return {
            "contract_version": 1,
            "mode": "dry_run",
            "request_id": "ft-test-1",
            "operation": "video_generation",
            "stage": "preflight",
            "route": "protocol",
            "budget": {"max_attempts": 1, "max_points": 35, "spent_points": 0},
        }

    def test_dry_run_never_allows_paid_task(self):
        result = decide(self.base()).as_dict("ft-test-1", self.base()["budget"])
        self.assertEqual(result["decision"], "deny")
        self.assertFalse(result["would_create_task"])
        self.assertEqual(result["max_new_tasks"], 0)
        self.assertEqual(result["reason_code"], "captcha_not_indicated")

    def test_auth_failure_is_circuit_open(self):
        req = self.base()
        req["prior_upstream_status"] = "401"
        result = decide(req)
        self.assertEqual(result.reason_code, "auth_failure_circuit_open")

    def test_explicit_captcha_can_use_local_route(self):
        req = self.base()
        req.update(route="browser", prior_error_category="captcha_indicated")
        result = decide(req)
        self.assertEqual(result.decision, "allow_local")
        self.assertEqual(result.provider, "local")

    def test_budget_exhaustion_denies(self):
        req = self.base()
        req["budget"] = {"max_attempts": 1, "max_points": 35, "spent_points": 35}
        result = decide(req)
        self.assertEqual(result.reason_code, "budget_exhausted")

    def test_non_dry_run_is_denied(self):
        req = self.base()
        req["mode"] = "authorize"
        self.assertEqual(decide(req).reason_code, "policy_unavailable")


if __name__ == "__main__":
    unittest.main()
