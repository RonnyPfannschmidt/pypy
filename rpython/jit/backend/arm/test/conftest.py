"""
This disables the backend tests on non ARMv7 platforms.
Note that you need "--slow" to run translation tests.
"""
import os
import pytest
from rpython.jit.backend import detect_cpu

cpu = detect_cpu.autodetect()
IS_ARMv7 = cpu.startswith('arm')
THIS_DIR = os.path.dirname(__file__)

@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(path, config):
    path = str(path)
    if not IS_ARMv7:
        if os.path.commonprefix([path, THIS_DIR]) == THIS_DIR:  # workaround for bug in pytest<3.0.5
            return True

class SkippedModule(pytest.Module):
    def collect(self):
        pytest.skip("ARMv7 tests skipped: cpu is %r" % (cpu,),
                    allow_module_level=True)

def pytest_pycollect_makemodule(path, parent):
    # files named on the command line bypass pytest_ignore_collect; some of
    # them cannot even be imported on another cpu
    if not IS_ARMv7:
        return SkippedModule(path, parent)
