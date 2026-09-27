"""RPython's str and unicode on Python 2 and Python 3 hosts."""
import sys

import py

from rpython.annotator import model as annmodel
from rpython.annotator.annrpython import RPythonAnnotator
from rpython.rtyper.test.test_llinterp import interpret
from rpython.tool.twothree import unichr, unicode

py3_only = py.test.mark.skipif(sys.version_info[0] < 3,
                               reason="Python 3 hosts only")


def annotate(func, argtypes):
    return RPythonAnnotator().build_types(func, argtypes)


def test_unicode_constant():
    C = unicode('abc')
    def f():
        return C
    assert isinstance(annotate(f, []), annmodel.SomeUnicodeString)

def test_str_constant():
    C = str('abc')
    def f():
        return C
    assert isinstance(annotate(f, []), annmodel.SomeString)

def test_bytes_constant():
    C = b'abc'
    def f(n):
        return C[n]
    assert isinstance(annotate(f, [int]), annmodel.SomeChar)
    assert interpret(f, [1]) == 'b'

def test_isinstance_str_is_not_unicode():
    def f(n):
        return isinstance(chr(n) + chr(n), unicode)
    s = annotate(f, [int])
    assert s.is_constant() and s.const is False

def test_isinstance_unicode_is_not_str():
    def f(n):
        return isinstance(unichr(n) + unichr(n), str)
    s = annotate(f, [int])
    assert s.is_constant() and s.const is False

def test_unichr_is_unichar():
    def f(n):
        return ord(unichr(n)), len(unichr(n) + unichr(n + 1))
    res = interpret(f, [0x20ac])
    assert (res.item0, res.item1) == (0x20ac, 2)

@py3_only
def test_str_beyond_latin1_is_rejected():
    C = chr(0x20ac) + 'x'
    def f():
        return C
    with py.test.raises(annmodel.AnnotatorError) as excinfo:
        annotate(f, [])
    assert 'latin-1' in str(excinfo.value)

def test_unicode_call():
    def f(i):
        return unicode('hello')[i]
    assert isinstance(annotate(f, [int]), annmodel.SomeUnicodeCodePoint)
    assert interpret(f, [1]) == u'e'

# ____________________________________________________________
# the flow space's text policy (rpython/flowspace/textpolicy.py)

from rpython.rlib.objectmodel import text_policy

U_GLOBAL = u'module-level'
S_GLOBAL = 'module-level'

def test_prefix_policy_literals():
    def f(n):
        if n:
            return u'abc'
        return u'x' + u'y'
    assert isinstance(annotate(f, [int]), annmodel.SomeUnicodeString)
    def g(n):
        if n:
            return 'abc'
        return 'x' + 'y'
    assert isinstance(annotate(g, [int]), annmodel.SomeString)

def test_prefix_policy_mixed_tuple():
    def f(n):
        t = (u'p', 'q')
        return t[n & 1]
    with py.test.raises(annmodel.UnionError):
        annotate(f, [int])

def test_prefix_policy_globals():
    def f():
        return U_GLOBAL
    assert isinstance(annotate(f, []), annmodel.SomeUnicodeString)
    def g():
        return S_GLOBAL
    assert isinstance(annotate(g, []), annmodel.SomeString)

@py3_only
def test_str_policy():
    @text_policy('str')
    def f():
        return u'abc'
    assert isinstance(annotate(f, []), annmodel.SomeString)

@py3_only
def test_unicode_policy():
    @text_policy('unicode')
    def f():
        return 'abc'
    assert isinstance(annotate(f, []), annmodel.SomeUnicodeString)

def test_keywords_stay_str():
    def g(a=0, k=0):
        return a + k
    @text_policy('prefix')
    def f(n):
        return g(n, k=1)
    assert isinstance(annotate(f, [int]), annmodel.SomeInteger)

def test_unicode_literal_rtyped():
    def f(n):
        s = u'\u20ac' + unichr(n)
        return len(s) * 1000 + ord(s[0]) - 0x20ac + ord(s[1])
    assert interpret(f, [65]) == 2065
