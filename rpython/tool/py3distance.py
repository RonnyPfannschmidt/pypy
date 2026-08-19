"""Measure how far the RPython tree is from being importable on Python 3.

This is a reporting tool, not a porting tool.  It counts occurrences of
constructs that are valid Python 2 but are either a syntax error on Python 3
or silently mean something else there.  The point is to have a single number
per category so that individual clean-up changes can state what they remove,
and so that a checkout can be prevented from drifting back.

Everything it counts is a construct with a spelling that is valid and
semantically identical on both Python 2 and Python 3, so every count can be
driven to zero without ever forking the source.

Usage::

    python rpython/tool/py3distance.py                 # report, whole tree
    python rpython/tool/py3distance.py rpython/rlib    # report, subtree
    python rpython/tool/py3distance.py --check origin/main

``--check`` re-runs the report against a git ref and fails if any category
grew.  It stores no baseline: the comparison is always against a ref, so
independent changes never conflict over a checked-in number.

Runs on Python 2.7 and on Python 3.  The tokenizer is grammar-agnostic, so a
Python 3 host can measure Python 2 sources and vice versa.
"""

from __future__ import print_function

import io
import os
import re
import subprocess
import sys
import tokenize
import warnings

# Files that are deliberately written in Python 2 syntax because they are
# fixtures testing that the flow space accepts it.  They must never be ported.
EXCLUDED = (
    'rpython/annotator/test/test_annrpython_py2.py',
    'rpython/flowspace/test/test_objspace_py2.py',
)

PY2_STDLIB = (
    '__builtin__ UserDict UserList UserString StringIO cStringIO cPickle '
    'ConfigParser Queue SocketServer Cookie cookielib copy_reg thread '
    'dummy_thread urllib2 urlparse HTMLParser htmlentitydefs commands md5 '
    'sha new sets whichdb anydbm dumbdbm exceptions'
).split()

PY2_BUILTINS = (
    'long unicode basestring unichr xrange cmp execfile raw_input apply '
    'buffer reload intern'
).split()

# (name, compiled regex, description).  Each is matched against the source
# with comments and string contents blanked out, so occurrences inside
# docstrings or C source templates are not counted.
CATEGORIES = [
    ('tuple_params',
     re.compile(r'\bdef\s+\w+\s*\(\s*(?:[^()]*?,\s*)?\('),
     'def f((a, b)): tuple parameter unpacking'),
    ('lambda_tuple_params',
     re.compile(r'\blambda\s*\('),
     'lambda (a, b): tuple parameter unpacking'),
    ('print_statement',
     re.compile(r'(?m)^\s*print(?:\s+[^\s=(]|\s*$|\s*>>)'),
     'print statement instead of print function'),
    ('exec_statement',
     re.compile(r'(?m)^\s*exec\s+[^\s(]'),
     'exec statement instead of exec function'),
    ('raise_comma',
     re.compile(r'(?m)^\s*raise\s+[\w.]+\s*,'),
     'raise E, v instead of raise E(v)'),
    ('octal_literal',
     # (?<![eE][+-]) so that the tail of a float like 6.5e+04 is not counted
     re.compile(r'(?<![\w.])(?<![eE][+-])0[0-7]+(?![\w.])'),
     '0755 instead of 0o755'),
    ('long_literal',
     re.compile(r'(?<![\w.])(?:0[xX][0-9a-fA-F]+|\d+)[lL](?![\w])'),
     '10L / 0xffL long literal suffix'),
    ('backtick_repr',
     re.compile(r'`'),
     '`x` instead of repr(x)'),
    ('ne_operator',
     re.compile(r'<>'),
     '<> instead of !='),
    ('has_key',
     re.compile(r'\.has_key\s*\('),
     'd.has_key(k) instead of k in d'),
    ('dict_iter_methods',
     re.compile(r'\.iter(?:items|keys|values)\s*\('),
     'd.iteritems() and friends'),
    ('metaclass_attr',
     re.compile(r'(?m)^\s*__metaclass__\s*='),
     '__metaclass__ = M class attribute'),
    ('py2_stdlib_import',
     re.compile(r'(?m)^\s*(?:import|from)\s+(?:%s)\b' % '|'.join(PY2_STDLIB)),
     'import of a module renamed in Python 3'),
    ('py2_builtin',
     re.compile(r'(?<![\w.])(?:%s)(?![\w])' % '|'.join(PY2_BUILTINS)),
     'use of a builtin removed in Python 3'),
]


def blank_strings_and_comments(source):
    """Return source with comments dropped and string contents blanked.

    Keeps line and column structure so that line-anchored patterns still
    work.  Falls back to returning the source unchanged if it cannot be
    tokenized at all.
    """
    try:
        readline = io.StringIO(source).readline
        tokens = list(tokenize.generate_tokens(readline))
    except Exception:
        return source
    lines = source.split('\n')
    out = [list(line) for line in lines]
    for ttype, tstr, start, end, _ in tokens:
        if ttype not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (srow, scol), (erow, ecol) = start, end
        for row in range(srow, erow + 1):
            if row - 1 >= len(out):
                break
            line = out[row - 1]
            lo = scol if row == srow else 0
            hi = ecol if row == erow else len(line)
            for col in range(lo, min(hi, len(line))):
                if line[col] != ' ':
                    line[col] = 'x'
    return '\n'.join(''.join(line) for line in out)


def read(path):
    with io.open(path, encoding='latin-1') as f:
        return f.read()


def iter_files(roots):
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for name in sorted(filenames):
                if not name.endswith('.py'):
                    continue
                path = os.path.join(dirpath, name)
                if path.replace(os.sep, '/') in EXCLUDED:
                    continue
                yield path


def measure(roots):
    """Return {category: (hits, files)} plus the py3 syntax-error count."""
    counts = dict((name, [0, 0]) for name, _, _ in CATEGORIES)
    counts['py3_syntax_error'] = [0, 0]
    for path in iter_files(roots):
        source = read(path)
        code = blank_strings_and_comments(source)
        for name, pattern, _ in CATEGORIES:
            n = len(pattern.findall(code))
            if n:
                counts[name][0] += n
                counts[name][1] += 1
        if sys.version_info[0] >= 3:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    compile(source, path, 'exec', dont_inherit=True)
            except SyntaxError:
                counts['py3_syntax_error'][0] += 1
                counts['py3_syntax_error'][1] += 1
            except Exception:
                pass
    return counts


DESCRIPTIONS = dict((name, doc) for name, _, doc in CATEGORIES)
DESCRIPTIONS['py3_syntax_error'] = 'files that do not parse on Python 3'


def report(counts, out=sys.stdout):
    order = [name for name, _, _ in CATEGORIES] + ['py3_syntax_error']
    width = max(len(name) for name in order)
    print('%-*s %8s %7s  %s' % (width, 'category', 'hits', 'files', 'meaning'),
          file=out)
    print('-' * (width + 60), file=out)
    total = 0
    for name in order:
        hits, files = counts[name]
        total += hits
        print('%-*s %8d %7d  %s' % (width, name, hits, files,
                                    DESCRIPTIONS[name]), file=out)
    print('-' * (width + 60), file=out)
    print('%-*s %8d' % (width, 'total', total), file=out)
    return total


def measure_ref(ref, roots):
    """Measure the tree as of a git ref, in a temporary worktree."""
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix='py3distance-')
    try:
        subprocess.check_call(
            ['git', 'worktree', 'add', '--detach', '--quiet', tmp, ref])
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            return measure(roots)
        finally:
            os.chdir(cwd)
    finally:
        subprocess.call(['git', 'worktree', 'remove', '--force', tmp],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    args = list(argv[1:])
    ref = None
    if '--check' in args:
        i = args.index('--check')
        args.pop(i)
        if i >= len(args):
            print('--check needs a git ref', file=sys.stderr)
            return 2
        ref = args.pop(i)
    roots = args or ['rpython']

    counts = measure(roots)
    total = report(counts)
    if ref is None:
        return 0

    before = measure_ref(ref, roots)
    print(file=sys.stdout)
    print('comparing against %s:' % ref)
    grew = []
    for name in sorted(counts):
        delta = counts[name][0] - before[name][0]
        if delta > 0:
            grew.append((name, before[name][0], counts[name][0]))
        elif delta < 0:
            print('  %-24s %6d -> %-6d (%+d)'
                  % (name, before[name][0], counts[name][0], delta))
    if grew:
        print()
        for name, was, now in grew:
            print('  REGRESSION %-20s %6d -> %-6d (+%d)'
                  % (name, was, now, now - was), file=sys.stderr)
        return 1
    print('  no category grew (total %d)' % total)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
