import unittest
from unittest.mock import Mock
from core.personal_watchdog import PersonalControllerGuard


class PersonalGuardTests(unittest.TestCase):
    def test_unknown_three_times_stops_only_once(self):
        stop = Mock(return_value={'ok': True})
        guard = PersonalControllerGuard(stop)
        for _ in range(2):
            self.assertEqual('controller_unknown', guard.observe({'ok': False})['action'])
        self.assertEqual('stop_personal_on_controller_loss', guard.observe({'ok': False})['action'])
        guard.observe({'ok': False})
        stop.assert_called_once()

    def test_manual_halt_never_invokes_callback(self):
        stop = Mock()
        guard = PersonalControllerGuard(stop)
        for _ in range(4):
            self.assertEqual('respect_manual_halt', guard.observe({}, manual_halt=True)['action'])
        stop.assert_not_called()

    def test_healthy_sample_resets_counter(self):
        stop = Mock()
        guard = PersonalControllerGuard(stop)
        guard.observe({})
        guard.observe({'ok': True})
        guard.observe({}); guard.observe({})
        stop.assert_not_called()
