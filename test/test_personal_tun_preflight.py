import unittest
from core.personal_tun_preflight import check_preflight, BUSINESS_EXE
from core.personal_tun_isolation import build_isolated_candidate
from test.test_personal_route import fixture


class PreflightTests(unittest.TestCase):
    def check(self, **kwargs):
        args = dict(executable=r'D:\Program Files\AgentProxyHub\personal\mihomo.exe',
                    manual_halt=False, business_tun=False, occupied_ports=[],
                    emergency_stop_covers_personal=True)
        args.update(kwargs)
        return check_preflight(build_isolated_candidate(fixture()), **args)

    def test_halt_has_priority(self):
        self.assertEqual('manual_halt', self.check(manual_halt=True)['code'])

    def test_identity_and_emergency_stop_required(self):
        self.assertEqual('shared_executable_identity', self.check(executable=str(BUSINESS_EXE))['code'])
        self.assertEqual('personal_emergency_stop_not_installed',
                         self.check(emergency_stop_covers_personal=False)['code'])

    def test_arbitrary_personal_executable_refused(self):
        self.assertEqual('personal_executable_not_allowlisted',
                         self.check(executable=r'C:\other\mihomo.exe')['code'])

    def test_unknown_business_and_busy_port_refused(self):
        self.assertFalse(self.check(business_tun=None)['ok'])
        self.assertEqual('controller_conflict', self.check(occupied_ports=[21919])['code'])

    def test_pass_is_not_runtime_acceptance(self):
        result = self.check()
        self.assertTrue(result['ok'])
        self.assertFalse(result['started'])
        self.assertFalse(result['gemini_noninterference_verified'])
