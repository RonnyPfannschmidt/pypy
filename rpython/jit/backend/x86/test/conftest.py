import os
import pytest
from rpython.jit.backend import detect_cpu

cpu = detect_cpu.autodetect()
IS_X86 = cpu.startswith('x86')
THIS_DIR = os.path.dirname(__file__)

@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(path, config):
    path = str(path)
    if not IS_X86:
        if os.path.commonprefix([path, THIS_DIR]) == THIS_DIR:  # workaround for bug in pytest<3.0.5
            return True

class SkippedModule(pytest.Module):
    def collect(self):
        pytest.skip("X86 tests skipped: cpu is %r" % (cpu,),
                    allow_module_level=True)

def pytest_pycollect_makemodule(path, parent):
    # files named on the command line bypass pytest_ignore_collect; some of
    # them cannot even be imported on another cpu
    if not IS_X86:
        return SkippedModule(path, parent)

def pytest_runtest_setup(item):
    if cpu == 'x86_64':
        if os.name == "nt":
            pytest.skip("Windows cannot allocate non-reserved memory")
        from rpython.rtyper.lltypesystem import ll2ctypes
        ll2ctypes.do_allocation_in_far_regions()
