import unittest
from unittest.mock import patch
from core.tun_controller import TunController


class ControllerTest(unittest.TestCase):
    def controller(self):
        with patch('core.tun_controller.runtime_controller_auth', return_value=('http://127.0.0.1:21909', {})):
            return TunController()

    def test_already_off_performs_no_patch(self):
        c = self.controller()
        with patch.object(c, 'request', return_value={'tun': {'enable': False}}) as req:
            self.assertTrue(c.disable_tun()['ok'])
            self.assertEqual(req.call_count, 1)

    def test_disable_checks_result(self):
        c = self.controller()
        with patch.object(c, 'request', side_effect=[{'tun': {'enable': True}}, {}, {'tun': {'enable': False}}]) as req:
            self.assertTrue(c.disable_tun()['ok'])
            self.assertEqual(req.call_args_list[1].args, ('PATCH', '/configs', {'tun': {'enable': False}}))

    def test_bad_controller_reports_unknown(self):
        c = self.controller()
        with patch.object(c, 'request', side_effect=TimeoutError()):
            self.assertIsNone(c.status()['tun_enabled'])
            self.assertFalse(c.disable_tun()['ok'])

    def test_snapshot_outside_backup_root_rejected(self):
        c = self.controller()
        with patch.object(c, 'request') as req:
            self.assertEqual(c.reload_disabled_snapshot(r'D:\other\config.yaml')['code'], 'backup_path_required')
            req.assert_not_called()

    def test_failed_verification_not_success(self):
        c = self.controller()
        with patch.object(c, 'request', side_effect=[{'tun': {'enable': True}}, {}, {'tun': {'enable': True}}]):
            self.assertFalse(c.disable_tun()['ok'])


if __name__ == '__main__':
    unittest.main()
