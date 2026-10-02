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

    def test_dns_and_existing_connections_are_excluded(self):
        b = self.business()
        b['dns'] = {'nameserver': ['https://doh.example/dns-query', 'https://223.5.5.5/dns-query']}
        c, _ = apply_exclusions(build_isolated_candidate(b), b,
                               {'node.example': ['5.6.7.8'], 'doh.example': ['9.9.9.9']},
                               active_addresses=['43.207.231.45', '127.0.0.1'])
        for address in ['9.9.9.9/32', '223.5.5.5/32', '43.207.231.45/32']:
            self.assertIn(address, c['tun']['route-exclude-address'])
        self.assertIn('doh.example', c['dns']['fake-ip-filter'])

    def test_missing_or_fake_dns_fails_closed(self):
        b = self.business(); c = build_isolated_candidate(b)
        for resolved in [{}, {'node.example': ['198.19.0.8']}]:
            with self.assertRaises(ValueError):
                apply_exclusions(c, b, resolved)
