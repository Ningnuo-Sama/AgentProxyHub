import unittest
from core.business_route_exclusions import apply_exclusions
from core.personal_tun_isolation import build_isolated_candidate
from test.test_personal_route import fixture


class ExclusionTests(unittest.TestCase):
    def business(self):
        b = fixture(); b['proxies'] = [{'server': 'node.example'}, {'server': '1.2.3.4'}]
        return b

    def test_exact_routes_and_dns_filter_without_business_change(self):
        b = self.business(); c = build_isolated_candidate(b)
        updated, evidence = apply_exclusions(c, b, {'node.example': ['5.6.7.8']})
        self.assertIn('5.6.7.8/32', updated['tun']['route-exclude-address'])
        self.assertIn('1.2.3.4/32', updated['tun']['route-exclude-address'])
        self.assertIn('node.example', updated['dns']['fake-ip-filter'])
        self.assertNotIn('node.example', c['dns']['fake-ip-filter'])
        self.assertFalse(evidence['runtime_routes_verified'])

    def test_missing_or_fake_dns_fails_closed(self):
        b = self.business(); c = build_isolated_candidate(b)
        for resolved in [{}, {'node.example': ['198.19.0.8']}]:
            with self.assertRaises(ValueError):
                apply_exclusions(c, b, resolved)
