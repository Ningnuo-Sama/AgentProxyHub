"""独立个人TUN配置契约；不启动进程、不读取凭据、不改业务配置。"""
import secrets

FIXED_PORTS = frozenset(range(21001, 21081)) | frozenset(range(22001, 22046))


def build_isolated_candidate(business, *, port=21012, controller_port=21919):
    """仅借用现有loopback SOCKS出口。默认关闭，须完成防环与业务无干扰验收。"""
    if port not in FIXED_PORTS:
        raise ValueError('unknown_business_port')
    if controller_port in FIXED_PORTS or controller_port in (21909, 39999):
        raise ValueError('controller_conflicts_with_business')
    from .personal_route import fixed_listener_map
    fixed_listener_map(business)
    if business.get('tun', {}).get('enable'):
        raise ValueError('business_tun_must_be_disabled')
    interface = business.get('interface-name')
    if not isinstance(interface, str) or not interface:
        raise ValueError('business_physical_interface_required')
    # 业务内核绑定物理接口；仍需实测其上游连接不被个人TUN回捕。
    return {
        'mode': 'rule', 'log-level': 'warning', 'ipv6': False,
        'external-controller': f'127.0.0.1:{controller_port}',
        'secret': secrets.token_hex(24),
        'allow-lan': False,
        'proxies': [{'name': 'BUSINESS-SOCKS', 'type': 'socks5',
                     'server': '127.0.0.1', 'port': port, 'udp': True}],
        'proxy-groups': [{'name': 'PERSONAL', 'type': 'select', 'proxies': ['BUSINESS-SOCKS']}],
        'dns': {'enable': True, 'ipv6': False, 'enhanced-mode': 'fake-ip',
                'fake-ip-range': '198.19.0.1/16',
                'fake-ip-filter': ['+.cn', '+.lan', '+.local'],
                'nameserver': ['https://223.5.5.5/dns-query'],
                'proxy-server-nameserver': ['https://223.5.5.5/dns-query']},
        'tun': {'enable': False, 'device': 'APH-Personal', 'stack': 'gvisor',
                'auto-route': True, 'auto-detect-interface': True,
                'inet4-address': ['198.19.0.1/30'], 'dns-hijack': ['any:53'],
                'route-exclude-address': ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12',
                                          '192.168.0.0/16', '169.254.0.0/16']},
        'rules': ['IP-CIDR,127.0.0.0/8,DIRECT,no-resolve',
                  'GEOIP,lan,DIRECT,no-resolve', 'GEOSITE,cn,DIRECT',
                  'GEOIP,cn,DIRECT', 'MATCH,PERSONAL'],
    }
