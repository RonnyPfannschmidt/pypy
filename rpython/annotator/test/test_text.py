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
