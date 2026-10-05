"""
Bytecode handling classes and functions for use by the flow space.
"""
import dis
import opcode
from opcode import EXTENDED_ARG, HAVE_ARGUMENT
from rpython.tool.stdlib_opcode import host_bytecode_spec
from rpython.flowspace.argument import Signature

try:
    from __pypy__ import _promote
except ImportError:
    _promote = lambda x: x

CO_GENERATOR = 0x0020
CO_VARARGS = 0x0004
CO_VARKEYWORDS = 0x0008

def cpython_code_signature(code):
    "([list-of-arg-names], vararg-name-or-None, kwarg-name-or-None)."
    argcount = code.co_argcount
    argnames = list(code.co_varnames[:argcount])
    if code.co_flags & CO_VARARGS:
        varargname = code.co_varnames[argcount]
        argcount += 1
    else:
        varargname = None
    if code.co_flags & CO_VARKEYWORDS:
        kwargname = code.co_varnames[argcount]
        argcount += 1
    else:
        kwargname = None
    return Signature(argnames, varargname, kwargname)


class BytecodeCorruption(Exception):
    pass

HASJREL = bytearray([_opnum in opcode.hasjrel for _opnum in range(256)])

HAS_GET_INSTRUCTIONS = hasattr(dis, 'get_instructions')
JUMP_OPCODES = frozenset(getattr(opcode, 'hasjump',
                                 opcode.hasjrel + opcode.hasjabs))


_ARGUMENT_DECODERS = {}

def _decodes(*opnames):
    def register(func):
        for opname in opnames:
            _ARGUMENT_DECODERS[opname] = func
        return func
    return register

def _normalize(instr, code):
    """(opname, oparg) of a dis instruction, as the handlers take them.

    The handlers get one encoding for all hosts; the host-specific
    encodings of the arguments are unpacked here.
    """
    decoder = _ARGUMENT_DECODERS.get(instr.opname)
    if decoder is not None:
        return decoder(instr, code)
    if instr.opcode in JUMP_OPCODES:
        return instr.opname, instr.argval
    if instr.arg is None:
        return instr.opname, 0
    return instr.opname, instr.arg

@_decodes('LOAD_FAST_LOAD_FAST', 'LOAD_FAST_BORROW_LOAD_FAST_BORROW',
          'STORE_FAST_LOAD_FAST', 'STORE_FAST_STORE_FAST')
def _decode_two_locals(instr, code):
    return instr.opname, (instr.arg >> 4, instr.arg & 15)

@_decodes('LOAD_DEREF', 'STORE_DEREF', 'DELETE_DEREF', 'LOAD_CLOSURE')
def _decode_free_variable(instr, code):
    # Python 3.11+ numbers these across locals, cells and free variables.
    # RPython functions have no cell variables, so an index into
    # co_freevars means the same on every host.
    return instr.opname, code.co_freevars.index(instr.argval)


def decode_instructions(code):
    """Decode a host code object with the dis module (Python 3 hosts).

    Returns ({offset: (next_offset, opname, oparg)}, exception_entries).
    dis resolves what differs between bytecode versions: EXTENDED_ARG,
    inline cache entries and the unit and direction of jumps.  The
    exception entries are (start, end, target, depth, lasti) tuples, with
    'end' exclusive, from the exception table of CPython 3.11 and later.
    """
    instrs = list(dis.get_instructions(code))
    table = {}
    next_offset = len(code.co_code)
    decoded = None
    for instr in reversed(instrs):
        if instr.opname == 'EXTENDED_ARG':
            # dis already folded the prefix into the argument of the
            # instruction that follows; jumps may still target the prefix
            table[instr.offset] = decoded
        else:
            opname, oparg = _normalize(instr, code)
            decoded = (next_offset, opname, oparg)
            table[instr.offset] = decoded
        next_offset = instr.offset
    bytecode = dis.Bytecode(code)
    exception_entries = tuple(
        (entry.start, entry.end, entry.target, entry.depth, entry.lasti)
        for entry in getattr(bytecode, 'exception_entries', ()))
    return table, exception_entries


class HostCode(object):
    """
    A wrapper around a native code object of the host interpreter
    """
    opnames = tuple(host_bytecode_spec.method_names)

    def __init__(self, argcount, nlocals, stacksize, flags,
                 code, consts, names, varnames, filename,
                 name, firstlineno, freevars,
                 instructions=None, exception_entries=()):
        """Initialize a new code object"""
        assert nlocals >= 0
        self.co_argcount = argcount
        self.co_nlocals = nlocals
        self.co_stacksize = stacksize
        self.co_flags = flags
        self.co_code = code
        self.consts = consts
        self.names = names
        self.co_varnames = varnames
        self.co_freevars = freevars
        self.co_filename = filename
        self.co_name = name
        self.co_firstlineno = firstlineno
        self.instructions = instructions
        self.exception_entries = exception_entries
        self.signature = cpython_code_signature(self)

    @classmethod
    def _from_code(cls, code):
        """Initialize the code object from a real (CPython) one.
        """
        if HAS_GET_INSTRUCTIONS:
            instructions, exception_entries = decode_instructions(code)
        else:
            instructions, exception_entries = None, ()
        return cls(code.co_argcount,
                   code.co_nlocals,
                   code.co_stacksize,
                   code.co_flags,
                   code.co_code,
                   list(code.co_consts),
                   list(code.co_names),
                   list(code.co_varnames),
                   code.co_filename,
                   code.co_name,
                   code.co_firstlineno,
                   list(code.co_freevars),
                   instructions,
                   exception_entries)

    @property
    def formalargcount(self):
        """Total number of arguments passed into the frame, including *vararg
        and **varkwarg, if they exist."""
        return self.signature.scope_length()

    def read(self, offset):
        """
        Decode the instruction starting at position ``offset``.

        Returns (next_offset, opname, oparg).  The oparg of a jump is
        the absolute offset of its target.
        """
        if self.instructions is not None:
            try:
                return self.instructions[offset]
            except KeyError:
                raise BytecodeCorruption("no instruction at offset %d" %
                                         (offset,))
        co_code = self.co_code
        opnum = ord(co_code[offset])
        next_offset = offset + 1

        if opnum >= HAVE_ARGUMENT:
            lo = ord(co_code[next_offset])
            hi = ord(co_code[next_offset + 1])
            next_offset += 2
            oparg = (hi * 256) | lo
        else:
            oparg = 0

        while opnum == EXTENDED_ARG:
            opnum = ord(co_code[next_offset])
            if opnum < HAVE_ARGUMENT:
                raise BytecodeCorruption
            lo = ord(co_code[next_offset + 1])
            hi = ord(co_code[next_offset + 2])
            next_offset += 3
            oparg = (oparg * 65536) | (hi * 256) | lo

        if HASJREL[opnum]:
            oparg += next_offset
        opname = self.opnames[_promote(opnum)]
        return next_offset, opname, oparg

    @property
    def is_generator(self):
        return bool(self.co_flags & CO_GENERATOR)
