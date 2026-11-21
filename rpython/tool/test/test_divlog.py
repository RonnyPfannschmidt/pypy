from rpython.annotator.annrpython import RPythonAnnotator
from rpython.tool import divlog


def test_log_records_operand_kinds(tmpdir, monkeypatch):
    logfile = tmpdir.join('divisions.log')
    monkeypatch.setattr(divlog, 'LOGFILE', str(logfile))
    def f(a, b, x):
        return a / b, x / 2.0
    RPythonAnnotator().build_types(f, [int, int, float])
    lines = logfile.read().splitlines()
    assert len(lines) == 2
    assert all(line.startswith(__file__.replace('.pyc', '.py') + ':')
               for line in lines)
    kinds = sorted(line.split(' ', 2)[2] for line in lines)
    assert kinds == ['float,float', 'int,int']

def test_no_log_by_default(monkeypatch):
    monkeypatch.setattr(divlog, 'LOGFILE', None)
    def f(a, b):
        return a / b
    RPythonAnnotator().build_types(f, [int, int])
