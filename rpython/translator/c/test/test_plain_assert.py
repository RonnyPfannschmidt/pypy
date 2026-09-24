"""How a failed plain assert behaves in translated code.

PYTEST_DONT_REWRITE: a rewritten assert raises an AssertionError subclass,
which propagates like an ordinary exception instead of aborting where it is
first caught, so these tests need the asserts left as they are.
"""
import re

from rpython.translator.c.test import test_typed
from rpython.translator.c.test.test_standalone import StandaloneTestsVerified

getcompiled = test_typed.TestTypedTestCase().getcompiled


def test_assert():
    def testfn(n):
        assert n >= 0

    f1 = getcompiled(testfn, [int])
    res = f1(0)
    assert res is None, repr(res)
    res = f1(42)
    assert res is None, repr(res)
    f1(-2, expected_exception_name='AssertionError')


class TestPlainAssertStandalone(StandaloneTestsVerified):

    def test_assertion_error_debug(self):
        def entry_point(argv):
            assert len(argv) != 1
            return 0
        t, cbuilder = self.compile(entry_point, debug=True)
        out, err = cbuilder.cmdexec("", expect_crash=True)
        assert out.strip() == ''
        lines = err.strip().splitlines()
        assert 'in pypy_g_RPyRaiseException: AssertionError' in lines

    def test_assertion_error_nondebug(self):
        def g(x):
            assert x != 1
        def f(argv):
            try:
                g(len(argv))
            finally:
                print 'done'
        def entry_point(argv):
            f(argv)
            return 0
        t, cbuilder = self.compile(entry_point, debug=False)
        out, err = cbuilder.cmdexec("", expect_crash=True)
        assert out.strip() == ''
        lines = err.strip().splitlines()
        idx = lines.index('Fatal RPython error: AssertionError') # assert found
        lines = lines[:idx+1]
        assert len(lines) >= 4
        l0, l1, l2 = lines[-4:-1]
        assert l0 == 'RPython traceback:'
        assert re.match(r'  File "\w+.c", line \d+, in f', l1)
        assert re.match(r'  File "\w+.c", line \d+, in g', l2)
        # The traceback stops at f() because it's the first function that
        # captures the AssertionError, which makes the program abort.
