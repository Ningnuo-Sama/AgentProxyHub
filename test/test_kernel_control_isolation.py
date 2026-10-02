import unittest
from unittest.mock import patch, Mock
from core import kernel_control as k


class KernelIsolationTests(unittest.TestCase):
    def test_personal_stop_does_not_target_business_or_set_halt(self):
        with patch.object(k.subprocess, 'run', return_value=Mock(returncode=0)) as run, \
             patch.object(k, 'set_halt') as halt:
            self.assertTrue(k.stop_personal_kernel()['ok'])
        command = run.call_args.args[0][-1]
        self.assertIn(k.PERSONAL_EXE, command)
        self.assertNotIn(k.OWNED_EXE, command)
        self.assertNotIn('Set-ItemProperty', command)
        halt.assert_not_called()

    def test_emergency_stop_covers_both_and_latches_first(self):
        events = []
        with patch.object(k, 'set_halt', side_effect=lambda x: events.append(('halt', x))), \
             patch.object(k.subprocess, 'run', side_effect=lambda *a, **kw: events.append(('run', a)) or Mock(returncode=0)):
            self.assertTrue(k.emergency_stop()['ok'])
        self.assertEqual(('halt', True), events[0])
        command = events[1][1][0][-1]
        self.assertIn(k.PERSONAL_EXE, command)
        self.assertIn(k.OWNED_EXE, command)
        self.assertNotIn('taskkill', command)

    def test_unowned_paths_refused(self):
        with self.assertRaises(ValueError):
            k._stop_command((r'C:\third-party\mihomo.exe',))
