import copy
import unittest
from core.personal_tun_isolation import build_isolated_candidate
from test.test_personal_route import fixture


class IsolationTests(unittest.TestCase):
    def test_no_business_listeners_or_credentials_copied(self):
        business = fixture()
        original = copy.deepcopy(business)
        c = build_isolated_candidate(business)
        self.assertEqual(business, original)
        self.assertNotIn('listeners', c)
        self.assertNotIn('TEST_ONLY_NOT_A_REAL_SECRET', str(c))
        self.assertNotEqual(business['secret'], c['secret'])
        self.assertEqual('127.0.0.1:21919', c['external-controller'])
        self.assertEqual('127.0.0.1', c['proxies'][0]['server'])
        self.assertEqual(21012, c['proxies'][0]['port'])
        self.assertFalse(c['tun']['enable'])
        self.assertEqual('APH-Personal', c['tun']['device'])

    def test_rejects_conflicts_and_unsafe_business(self):
        for kwargs in [{'port': 9999}, {'controller_port': 21909}, {'controller_port': 21012}]:
            with self.assertRaises(ValueError):
                build_isolated_candidate(fixture(), **kwargs)
        b = fixture(); b['tun'] = {'enable': True}
        with self.assertRaises(ValueError):
            build_isolated_candidate(b)
        b = fixture(); b.pop('interface-name')
        with self.assertRaises(ValueError):
            build_isolated_candidate(b)
