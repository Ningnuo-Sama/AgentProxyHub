"""锁内方向选择与结果确认；不切换实际网络。"""
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from core import personal_lifecycle as route


class ToggleTests(unittest.TestCase):
    def test_toggle_on_and_off(self):
        for before in (True, False):
            with patch.object(route, 'control_lock', return_value=nullcontext()), \
                 patch.object(route, 'status', side_effect=[{'known': True, 'active': before}, {'known': True, 'active': not before}]), \
                 patch.object(route, 'start', return_value={'ok': True}) as start, \
                 patch.object(route, 'stop', return_value={'ok': True}) as stop:
                result = route.toggle()
                self.assertTrue(result['ok'])
                self.assertEqual(start.call_count, int(not before))
                self.assertEqual(stop.call_count, int(before))

    def test_unknown_never_switches(self):
        with patch.object(route, 'control_lock', return_value=nullcontext()), \
             patch.object(route, 'status', return_value={'known': False, 'active': None}), \
             patch.object(route, 'start') as start, patch.object(route, 'stop') as stop:
            self.assertFalse(route.toggle()['ok'])
            start.assert_not_called()
            stop.assert_not_called()
