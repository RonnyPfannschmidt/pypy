import py

from rpython.flowspace.flowcontext import FlowingError
from rpython.flowspace.model import Constant
from rpython.translator.simplify import simplify_graph
from rpython.flowspace.test.test_objspace import Base


class TestFlowObjSpacePy3(Base):

    def test_raise_from_none(self):
        def f(x):
            try:
                x()
            except KeyError:
                raise ValueError from None
        self.codetest(f)

    def test_raise_from_cause(self):
        def f(x):
            try:
                x()
            except KeyError as e:
                raise ValueError from e
        with py.test.raises(FlowingError):
            self.codetest(f)

    def test_keyword_only_defaults(self):
        def f():
            return lambda *, k=1: k
        with py.test.raises(FlowingError) as excinfo:
            self.codetest(f)
        assert 'keyword-only' in str(excinfo.value)

    def test_comprehension_variable_is_restored(self):
        def f(xs):
            x = 5
            lst = [x + 1 for x in xs]
            return x
        graph = self.codetest(f)
        simplify_graph(graph)
        [link] = [link for link in graph.iterlinks()
                  if link.target is graph.returnblock]
        assert link.args == [Constant(5)]

    def test_percent_formatting(self):
        # compiled to f-string instructions since 3.12
        def f(x, y):
            return 'a %s b %r' % (x, y)
        graph = self.codetest(f)
        ops = self.all_operations(graph)
        assert ops == {'str': 1, 'repr': 1, 'add': 3}

    def test_fstring(self):
        def f(x):
            return f'{x}!{x!r}'
        graph = self.codetest(f)
        assert self.all_operations(graph) == {'str': 1, 'repr': 1, 'add': 2}

    def test_fstring_format_spec(self):
        def f(x):
            return f'{x:>3}'
        with py.test.raises(FlowingError):
            self.codetest(f)
