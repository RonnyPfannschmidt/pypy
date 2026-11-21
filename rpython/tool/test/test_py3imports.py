from rpython.tool import py3imports


def test_module_names_cover_packages_and_modules():
    names = py3imports.module_names(['rpython/tool'])
    assert 'rpython.tool' in names
    assert 'rpython.tool.py3imports' in names
    assert 'rpython/tool/test/test_py3imports.py' in names


def test_import_one_reports_success_and_the_failing_line(tmpdir):
    assert py3imports.import_one('rpython.tool.pairtype', str(tmpdir)) == (
        'rpython.tool.pairtype', {'ok': True})
    name, result = py3imports.import_one(
        'rpython/tool/test/cant_import_py3imports.py', str(tmpdir))
    assert not result['ok']
    assert result['where'] == 'rpython/tool/test/cant_import_py3imports.py:1'
    assert 'No module named' in result['error']


def test_report_counts_only_modules_that_import_in_the_base(capsys):
    results = {'a': {'ok': True},
               'b': {'ok': False, 'where': 'b.py:1', 'error': 'E'},
               'c': {'ok': False, 'where': 'c.py:1', 'error': 'E'}}
    base = {'a': {'ok': True}, 'b': {'ok': True},
            'c': {'ok': False, 'where': 'c.py:1', 'error': 'E'}}
    assert py3imports.report(results, base) == ['b']
    assert '1 of 2 modules import' in capsys.readouterr()[0]
