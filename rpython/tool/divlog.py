"""Log the divisions that the annotator sees, with their operand types.

For porting modules to 'from __future__ import division': without it,
'/' on two ints is floor division on Python 2 and must become '//',
while '/' on floats stays.  The annotator knows the operand types of
every division in RPython code, so a translation or a test run with

    RPYTHON_DIVISION_LOG=/path/to/log

appends one line per division it annotates:

    <file>:<line> <operation> <operand kinds>

e.g. 'rpython/rlib/rbigint.py:1234 div int,int'.  Operand kinds are
'int', 'float' or the annotation's class name.
"""
import os

LOGFILE = os.environ.get('RPYTHON_DIVISION_LOG')
DIVISIONS = frozenset(['div', 'inplace_div', 'truediv', 'inplace_truediv'])


def operand_kind(s_value):
    from rpython.annotator import model as annmodel
    if isinstance(s_value, (annmodel.SomeInteger, annmodel.SomeBool)):
        return 'int'
    if isinstance(s_value, annmodel.SomeFloat):
        return 'float'
    return type(s_value).__name__


def record(annotator, op):
    from rpython.tool.error import offset2lineno
    try:
        graph = annotator.bookkeeper.position_key[0]
        code = graph.func.__code__
    except (AttributeError, IndexError, TypeError):
        return
    lineno = offset2lineno(code, op.offset)
    kinds = ','.join([operand_kind(annotator.annotation(arg))
                      for arg in op.args])
    with open(LOGFILE, 'a') as f:
        f.write('%s:%d %s %s\n' % (code.co_filename, lineno, op.opname,
                                   kinds))
