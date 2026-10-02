import unittest
from core.tun_watchdog import Evidence, TunWatchdog


class WatchdogTest(unittest.TestCase):
    def evidence(self, **changes):
        fields = dict(controller_ok=True, dns_ok=True, direct_ok=True,
                      proxy_ok=True, local_services_ok=True, tun_enabled=True)
        fields.update(changes)
        return Evidence(**fields)

    def test_three_failures_and_only_one_rollback(self):
        calls = []
        dog = TunWatchdog(lambda: calls.append(1) or {'ok': True})
        bad = self.evidence(dns_ok=False)
        self.assertEqual(dog.observe(bad)['action'], 'observe')
        self.assertEqual(dog.observe(bad)['action'], 'observe')
        self.assertEqual(dog.observe(bad)['action'], 'rollback')
        self.assertEqual(dog.observe(bad)['action'], 'await_manual_enable')
        self.assertEqual(calls, [1])

    def test_manual_halt_never_revives(self):
        dog = TunWatchdog(lambda: self.fail('rollback should not run'))
        self.assertEqual(dog.observe(self.evidence(manual_halt=True))['action'], 'respect_manual_halt')
        self.assertEqual(dog.observe(self.evidence())['action'], 'await_manual_enable')

    def test_proxy_failure_not_system_failure(self):
        dog = TunWatchdog(lambda: self.fail('must not stop all services'))
        for _ in range(5):
            self.assertEqual(dog.observe(self.evidence(proxy_ok=False))['action'], 'healthy')

    def test_recovery_resets_failure_count(self):
        dog = TunWatchdog(lambda: {'ok': True})
        dog.observe(self.evidence(direct_ok=False))
        dog.observe(self.evidence())
        self.assertEqual(dog.observe(self.evidence(direct_ok=False))['failures'], 1)

    def test_rollback_error_is_latched(self):
        def broken():
            raise OSError('failure')
        dog = TunWatchdog(broken, threshold=1)
        self.assertEqual(dog.observe(self.evidence(controller_ok=False))['action'], 'rollback_failed')
        self.assertEqual(dog.observe(self.evidence(controller_ok=False))['action'], 'await_manual_enable')


if __name__ == '__main__':
    unittest.main()
