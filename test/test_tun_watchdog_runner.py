import subprocess
import unittest
from unittest.mock import Mock, patch
from tools.tun_watchdog_runner import collect, main


class RunnerTest(unittest.TestCase):
    def test_controller_unknown_stays_unknown(self):
        controller = Mock()
        controller.status.return_value = {'ok': False, 'tun_enabled': None}
        with patch('tools.tun_watchdog_runner.is_halted', return_value=False):
            evidence, _ = collect(controller, [])
        self.assertIsNone(evidence.tun_enabled)
        self.assertFalse(evidence.controller_ok)

    def test_dns_timeout_is_failed_probe_not_dead_monitor(self):
        controller = Mock()
        controller.status.return_value = {'ok': True, 'tun_enabled': True}
        with patch('tools.tun_watchdog_runner.is_halted', return_value=False), \
             patch('tools.tun_watchdog_runner.tcp_probe', return_value=True), \
             patch('subprocess.run', side_effect=subprocess.TimeoutExpired('dns', 5)):
            evidence, _ = collect(controller, [])
        self.assertFalse(evidence.dns_ok)
        self.assertTrue(evidence.tun_enabled)

    def test_halt_exits_without_probe(self):
        with patch('tools.tun_watchdog_runner.is_halted', return_value=True), \
             patch('tools.tun_watchdog_runner.TunController') as controller:
            with patch('sys.argv', ['runner', '--once']):
                self.assertEqual(main(), 0)
            controller.assert_called_once()


if __name__ == '__main__':
    unittest.main()
