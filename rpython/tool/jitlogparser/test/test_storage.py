from rpython.tool.jitlogparser.storage import LoopStorage

def test_load_codes(tmpdir):
    tmpdir.join("x.py").write("def f(): pass") # one code
    s = LoopStorage(str(tmpdir))
    assert s.load_code(str(tmpdir.join('x.py'))) == s.load_code('x.py')

