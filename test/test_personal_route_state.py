import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.personal_route_state import desired_on, set_desired, close_personal


class PersonalStateTests(unittest.TestCase):
    def test_missing_corrupt_and_explicit_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            self.assertFalse(desired_on(path))
            set_desired(True, path)
            self.assertTrue(desired_on(path))
            set_desired(False, path)
            self.assertFalse(desired_on(path))
            path.write_text('{broken')
            self.assertFalse(desired_on(path))

    def test_off_is_recorded_before_stop_and_failure_not_hidden(self):
        events = []
        with patch('core.personal_route_state.set_desired', side_effect=lambda x: events.append(('state', x))), \
             patch('core.kernel_control.stop_personal_kernel', side_effect=lambda: events.append(('stop',)) or {'ok': False}):
            result = close_personal()
        self.assertEqual([('state', False), ('stop',)], events)
        self.assertFalse(result['ok'])
        self.assertFalse(result['desired_on'])
