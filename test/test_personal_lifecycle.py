import unittest
from pathlib import Path
from unittest.mock import patch
from core import personal_lifecycle as life


class PersonalLifecycleTests(unittest.TestCase):
    def test_start_refuses_manual_halt_and_preserves_label(self):
        with patch.object(life, 'is_halted', return_value=True):
            result = life.start()
        self.assertFalse(result['ok'])
        self.assertEqual('停止內核', result['label'])

    def test_stop_uses_personal_route_state_and_label(self):
        with patch('core.personal_route_state.close_personal', return_value={'ok': True, 'desired_on': False}):
            result = life.stop()
        self.assertTrue(result['ok'])
        self.assertFalse(result['desired_on'])
        self.assertEqual('出海介入', result['label'])

    def test_start_does_not_restart_running_personal(self):
        with patch.object(life, 'is_halted', return_value=False), \
             patch.object(life, '_running', return_value=True), \
             patch.object(life, 'set_desired') as set_state:
            result = life.start()
        self.assertEqual('personal_already_running', result['code'])
        set_state.assert_called_once_with(True)
