import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from core.process_control_lock import process_control_lock


@unittest.skipUnless(os.name == 'nt', 'Windows文件锁')
class ControlLockTests(unittest.TestCase):
    def test_reentrant_and_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'control.lock'
            with process_control_lock(path):
                with process_control_lock(path):
                    pass
            with process_control_lock(path, timeout=.2):
                pass

    def test_real_child_cannot_acquire_until_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'control.lock'
            script = "from core.process_control_lock import process_control_lock; import sys\ntry:\n with process_control_lock(sys.argv[1],timeout=.15): pass\nexcept TimeoutError: sys.exit(7)"
            with process_control_lock(path):
                child = subprocess.run([sys.executable, '-c', script, str(path)], timeout=5)
                self.assertEqual(7, child.returncode)
            child = subprocess.run([sys.executable, '-c', script, str(path)], timeout=5)
            self.assertEqual(0, child.returncode)
