import py

from rpython.flowspace.flowcontext import FlowingError
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
