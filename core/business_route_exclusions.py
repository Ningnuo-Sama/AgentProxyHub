"""业务端点防回捕清单：仅变更个人候选，不改业务节点/绑定。"""
import copy
import ipaddress

FAKE_RANGE = ipaddress.ip_network('198.18.0.0/15')


def endpoint_hosts(business):
    hosts = set()
    for proxy in business.get('proxies', []):
        host = proxy.get('server')
        if not isinstance(host, str) or not host.strip():
            raise ValueError('business_endpoint_missing')
        hosts.add(host.strip())
    if not hosts:
        raise ValueError('business_endpoints_empty')
    return sorted(hosts)


def apply_exclusions(candidate, business, resolved):
    """resolved需由TUN关闭时的有界现场解析提供；地址更新后必须重验。"""
    c = copy.deepcopy(candidate)
    addresses = set()
    domains = []
    for host in endpoint_hosts(business):
        try:
            values = [str(ipaddress.ip_address(host))]
        except ValueError:
            values = resolved.get(host, [])
            domains.append(host)
        if not values:
            raise ValueError('business_endpoint_unresolved')
        for value in values:
            address = ipaddress.ip_address(value)
            if address.version == 4 and address in FAKE_RANGE:
                raise ValueError('business_endpoint_fake_ip')
            if address.is_unspecified or address.is_multicast:
                raise ValueError('unsafe_business_endpoint')
            addresses.add(str(address) + ('/32' if address.version == 4 else '/128'))
    routes = c['tun'].setdefault('route-exclude-address', [])
    routes[:] = sorted(set(routes) | addresses)
    filters = c['dns'].setdefault('fake-ip-filter', [])
    filters[:] = sorted(set(filters) | set(domains) | {'localhost', '+.localhost'})
    return c, {'hosts': len(endpoint_hosts(business)), 'excluded_addresses': len(addresses),
               'runtime_routes_verified': False, 'refresh_required_on_endpoint_change': True}
