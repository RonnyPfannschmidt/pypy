"""
This disables the backend tests on non ARM64 platforms.
Note that you need "--slow" to run translation tests.
"""
import os
import sys
import pytest
from rpython.jit.backend import detect_cpu

cpu = detect_cpu.autodetect()
IS_ARM64 = cpu.startswith('aarch64')
IS_MACOS = sys.platform == 'darwin'
IS_PYPY = 'pypyjit' in sys.builtin_module_names
THIS_DIR = os.path.dirname(__file__)

@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(path, config):
    path = str(path)
    if not IS_ARM64:
        if os.path.commonprefix([path, THIS_DIR]) == THIS_DIR:  # workaround for bug in pytest<3.0.5
            return True

class SkippedModule(pytest.Module):
    def collect(self):
        pytest.skip("ARM64 tests skipped: cpu is %r" % (cpu,),
                    allow_module_level=True)

def pytest_pycollect_makemodule(path, parent):
    # files named on the command line bypass pytest_ignore_collect; some of
    # them cannot even be imported on another cpu
    if not IS_ARM64:
        return SkippedModule(path, parent)

if IS_ARM64 and IS_MACOS and IS_PYPY:
    # This is done as well in the pypy/testrunner_cfg.py
    @pytest.fixture(autouse=True)
    def raise_if_jit():
        import pypyjit
        pypyjit.set_param("off")
