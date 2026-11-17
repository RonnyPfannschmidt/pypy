"""Import every module of a source tree and report which ones fail.

Usage:
    python rpython/tool/py3imports.py [--json OUT] [--compare BASE.json] [root ...]

Each module is imported in a fresh interpreter, so one module's side effects
cannot hide or cause another one's failure.  Failures are grouped by the
innermost frame inside the tree and the exception, because a handful of
module-level problems usually account for most of the failing modules.

Runs on Python 2 and Python 3.  Run it on Python 2 with --json to record which
modules import there, then on Python 3 with --compare to list the modules that
still fail on Python 3 but import on Python 2: that list is the work left.
"""

from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
from multiprocessing import cpu_count
from multiprocessing.pool import ThreadPool

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(os.path.dirname(HERE))

TIMEOUT = 120

CHILD = r'''
import json, sys, traceback
name, top = sys.argv[1], sys.argv[2]
def where(tb):
    frames = [f for f in traceback.extract_tb(tb) if f[0].startswith(top)]
    if not frames:
        return "?"
    return "%s:%d" % (frames[-1][0][len(top) + 1:], frames[-1][1])
try:
    if name.endswith(".py"):
        # not in a package: import it the way pytest does, by basename
        # with its directory at the front of sys.path
        import os
        path = os.path.join(top, name)
        sys.path.insert(0, os.path.dirname(path))
        __import__(os.path.basename(path)[:-3])
    else:
        __import__(name)
    result = {"ok": True}
except BaseException as e:
    msg = " ".join(("%s: %s" % (type(e).__name__, e)).split())[:200]
    result = {"ok": False, "where": where(sys.exc_info()[2]), "error": msg}
sys.stdout.write("\n@@py3imports@@" + json.dumps(result) + "\n")
'''


def module_names(roots):
    """Dotted names for modules inside packages, and paths ending in .py
    for the ones outside any package, such as tests in a directory without
    an __init__.py."""
    names = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(os.path.join(TOP, root)):
            dirnames[:] = sorted(d for d in dirnames
                                 if d != '_cache' and not d.startswith('.'))
            rel = os.path.relpath(dirpath, TOP)
            in_package = os.path.exists(os.path.join(dirpath, '__init__.py'))
            for fn in sorted(filenames):
                if not fn.endswith('.py'):
                    continue
                if not in_package:
                    names.append(os.path.join(rel, fn).replace(os.sep, '/'))
                elif fn == '__init__.py':
                    names.append(rel.replace(os.sep, '.'))
                else:
                    names.append(rel.replace(os.sep, '.') + '.' + fn[:-3])
    return names


def import_one(name, cwd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=TOP + os.pathsep + os.environ.get('PYTHONPATH', ''))
    cmd = [sys.executable, '-c', CHILD, name, TOP]
    if sys.platform != 'win32':
        cmd = ['timeout', str(TIMEOUT)] + cmd
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                            env=env, cwd=cwd)
    out = proc.communicate()[0].decode('utf-8', 'replace')
    marker = out.rfind('@@py3imports@@')
    if marker < 0:
        return name, {"ok": False, "where": "?",
                      "error": "no result, exit status %s" % proc.returncode}
    return name, json.loads(out[marker + len('@@py3imports@@'):])


def run(roots, jobs):
    # some modules are scripts that write files next to where they run
    cwd = tempfile.mkdtemp(prefix='py3imports-')
    pool = ThreadPool(jobs)
    try:
        return dict(pool.map(lambda name: import_one(name, cwd),
                             module_names(roots)))
    finally:
        pool.close()
        shutil.rmtree(cwd, ignore_errors=True)


def report(results, base=None):
    names = sorted(results)
    if base is not None:
        names = [n for n in names if base.get(n, {}).get('ok')]
    failed = [n for n in names if not results[n]['ok']]
    groups = {}
    for n in failed:
        key = (results[n]['where'], results[n]['error'])
        groups.setdefault(key, []).append(n)
    for (where, error), mods in sorted(groups.items(),
                                       key=lambda kv: (-len(kv[1]), kv[0])):
        print('%5d  %s  %s' % (len(mods), where, error))
    print('-' * 79)
    print('%d of %d modules import on Python %d.%d%s' % (
        len(names) - len(failed), len(names),
        sys.version_info[0], sys.version_info[1],
        ' (counting only those that import in the base)' if base else ''))
    return failed


def main(argv):
    out = base = None
    roots = []
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == '--json':
            out = args.pop(0)
        elif arg == '--compare':
            with open(args.pop(0)) as f:
                base = json.load(f)
        else:
            roots.append(arg)
    results = run(roots or ['rpython'], jobs=cpu_count())
    if out:
        with open(out, 'w') as f:
            json.dump(results, f, indent=1, sort_keys=True)
    report(results, base)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
