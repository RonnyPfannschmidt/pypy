from __future__ import print_function

import os
import py

from rpython.jit.tl.test import jitcrashers

path = os.path.join(os.path.dirname(__file__), "..", "targetpypyjit-c")
JIT_EXECUTABLE = py.path.local(path)
del path
CRASH_FILE = os.path.abspath(jitcrashers.__file__.rstrip("c"))

if not JIT_EXECUTABLE.check():
    py.test.skip("no JIT executable")

def setup_module(mod):
    mod._old_cwd = os.getcwd()
    os.chdir(str(JIT_EXECUTABLE.dirpath()))

def teardown_module(mod):
    os.chdir(mod._old_cwd)

def check_crasher(func_name):
    try:
        JIT_EXECUTABLE.sysexec(CRASH_FILE, func_name)
    except py.process.cmdexec.Error as e:
        print("stderr")
        print("------")
        print(e.err)
        print("stdout")
        print("------")
        print(e.out)
        raise

# Parametrized over sorted names, so the order is always consistent and
# reproducible.
@py.test.mark.parametrize('func_name', sorted(
    name for name in jitcrashers.__dict__ if name.startswith("jit_")))
def test_jit_crashers(func_name):
    check_crasher(func_name)
