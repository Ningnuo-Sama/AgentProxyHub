"""内核急停隔离契约测试（2026-10-19 个人出海模块移除后更新）。

移除内容：原 personal_stop / 覆盖两个内核的用例。
出海内核 personal/ 已下线，急停只针对业务内核 OWNED_EXE。

核心不变式：
1. 急停只按完整可执行路径精确匹配，绝不 taskkill /im mihomo.exe
2. 急停必须先写闩锁再执行，防止看门狗复活
3. 非白名单路径必须拒绝
4. 不得设系统代理 / PAC
"""
import unittest
from unittest.mock import patch, Mock
from core import kernel_control as k


class KernelIsolationTests(unittest.TestCase):
    def test_personal_exe_retired(self):
        """个人出海已下线：PERSONAL_EXE 与 stop_personal_kernel 必须不存在。"""
        self.assertFalse(hasattr(k, 'PERSONAL_EXE'),
                         '个人出海内核已移除，不应再暴露 PERSONAL_EXE')
        self.assertFalse(hasattr(k, 'stop_personal_kernel'),
                         '个人出海内核已移除，不应再暴露 stop_personal_kernel')

    def test_stop_command_only_allows_owned(self):
        """白名单只含业务内核。"""
        with self.assertRaises(ValueError):
            k._stop_command((r'D:\Program Files\AgentProxyHub\personal\mihomo.exe',))

    def test_emergency_stop_targets_business_only_and_latches_first(self):
        events = []
        with patch.object(k, 'set_halt', side_effect=lambda x: events.append(('halt', x))), \
             patch.object(k.subprocess, 'run', side_effect=lambda *a, **kw: events.append(('run', a)) or Mock(returncode=0)):
            self.assertTrue(k.emergency_stop()['ok'])
        self.assertEqual(('halt', True), events[0])
        command = events[1][1][0][-1]
        self.assertIn(k.OWNED_EXE, command)
        self.assertNotIn('taskkill', command)
        self.assertNotIn(r'personal\mihomo.exe', command)

    def test_unowned_paths_refused(self):
        with self.assertRaises(ValueError):
            k._stop_command((r'C:\third-party\mihomo.exe',))