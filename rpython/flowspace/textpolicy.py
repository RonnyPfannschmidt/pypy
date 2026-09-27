"""Which text constants stand for RPython unicode on Python 3 hosts.

On Python 2, 'abc' is an RPython str and u'abc' an RPython unicode.
Python 3 compiles both to the same str, so the flow space needs a policy
to tell them apart again:

- 'prefix' (the default) guesses from the source: a constant is unicode
  if the literal it comes from has the u prefix, as on Python 2.
- 'str' makes every text constant an RPython str.
- 'unicode' makes every text constant an RPython unicode.

A function chooses with its _text_policy_ attribute (see
rpython.rlib.objectmodel.text_policy), a module with a global
__rpython_text_policy__.  Constants that are unicode become instances of
twothree.unicode; plain strs stay RPython strs.  Python 2 hosts keep
their own literals and ignore the policy.
"""

import ast
import linecache

from rpython.tool.twothree import unicode

POLICIES = ('prefix', 'str', 'unicode')
# only Python 3 compiles 'abc' and u'abc' to the same type
PYTHON3_HOST = str is not bytes
DEFAULT_POLICY = 'prefix'


def policy_of(func):
    policy = getattr(func, '_text_policy_', None)
    if policy is None:
        policy = func.__globals__.get('__rpython_text_policy__',
                                      DEFAULT_POLICY)
    if policy not in POLICIES:
        raise ValueError("unknown text policy %r of %r" % (policy, func))
    return policy


def as_unicode(value):
    """value with its text made unicode: strs, and tuples and frozensets
    of them"""
    if type(value) is str:
        return unicode(value)
    if type(value) is tuple:
        return tuple([as_unicode(item) for item in value])
    if type(value) is frozenset:
        return frozenset([as_unicode(item) for item in value])
    return value


def has_text(value):
    if type(value) is str:
        return True
    if type(value) in (tuple, frozenset):
        return any(has_text(item) for item in value)
    return False


def source_segment(filename, positions):
    """The source text an instruction's positions cover, or None."""
    if positions is None or positions.lineno is None:
        return None
    lines = linecache.getlines(filename)
    if not lines or positions.end_lineno > len(lines):
        return None
    # the column offsets count UTF-8 bytes
    chunk = [line.encode('utf-8') for line in
             lines[positions.lineno - 1:positions.end_lineno]]
    if len(chunk) == 1:
        chunk[0] = chunk[0][positions.col_offset:positions.end_col_offset]
    else:
        chunk[0] = chunk[0][positions.col_offset:]
        chunk[-1] = chunk[-1][:positions.end_col_offset]
    return b''.join(chunk).decode('utf-8')


def literal_kinds(segment):
    """The string literals of a source segment, as a list of
    (value, is_unicode), or None if the segment does not parse."""
    try:
        tree = ast.parse(segment.strip(), mode='eval')
    except SyntaxError:
        return None
    return [(node.value, node.kind == 'u') for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and type(node.value) is str]


def type_by_prefix(value, segment):
    """value with the text that came from u'' literals made unicode"""
    kinds = literal_kinds(segment) if segment is not None else None
    if not kinds:
        return value
    if type(value) is str:
        # u'x' + 'y' was unicode on Python 2, too
        if any(is_unicode for _, is_unicode in kinds):
            return unicode(value)
        return value
    if type(value) is tuple and len(kinds) == len(value):
        # a folded tuple display, literal by literal
        return tuple([unicode(item) if is_unicode and type(item) is str
                      else item
                      for item, (_, is_unicode) in zip(value, kinds)])
    if all(is_unicode for _, is_unicode in kinds):
        return as_unicode(value)
    return value


def type_constant(value, policy, filename, positions):
    """The constant the flow space loads for a host constant."""
    if not PYTHON3_HOST or not has_text(value):
        return value
    if policy == 'str':
        return value
    if policy == 'unicode':
        return as_unicode(value)
    return type_by_prefix(value, source_segment(filename, positions))


_module_unicode_names = {}

def module_unicode_names(module_globals):
    """Names that the module assigns from u'' literals at its top level:
    the module-level constants that 'prefix' makes unicode."""
    filename = module_globals.get('__file__')
    if not filename:
        return frozenset()
    if filename.endswith(('.pyc', '.pyo')):
        filename = filename[:-1]
    try:
        return _module_unicode_names[filename]
    except KeyError:
        pass
    names = set()
    source = ''.join(linecache.getlines(filename))
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        tree = None
    if tree is not None:
        for node in tree.body:
            if isinstance(node, ast.Assign):
                has_u = any(isinstance(sub, ast.Constant) and
                            type(sub.value) is str and sub.kind == 'u'
                            for sub in ast.walk(node.value))
                if has_u:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
    result = _module_unicode_names[filename] = frozenset(names)
    return result


def type_global(value, name, policy, module_globals):
    """The constant the flow space loads for a module global."""
    if not PYTHON3_HOST or not has_text(value):
        return value
    if policy == 'unicode':
        return as_unicode(value)
    if policy == 'prefix' and name in module_unicode_names(module_globals):
        return as_unicode(value)
    return value
