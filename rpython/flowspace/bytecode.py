"""
Bytecode handling classes and functions for use by the flow space.
"""
import dis
import opcode
from opcode import EXTENDED_ARG, HAVE_ARGUMENT
from rpython.tool.stdlib_opcode import host_bytecode_spec
from rpython.flowspace.argument import Signature
from rpython.tool.twothree import builtins

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

@_decodes('COMPARE_OP')
def _decode_comparison(instr, code):
    # 3.12 shifts the operator by 4 bits, 3.13+ by 5 and adds a flag that
    # coerces the result to bool; dis names the operator either way
    operator = instr.argval
    if operator.startswith('bool('):
        operator = operator[len('bool('):-1]
    return instr.opname, opcode.cmp_op.index(operator)

@_decodes('BINARY_OP')
def _decode_binary_operator(instr, code):
    return instr.opname, instr.argrepr

@_decodes('FOR_ITER')
def _decode_for_iter(instr, code):
    if dis.stack_effect(instr.opcode, instr.arg, jump=True) > 0:
        # 3.12+: an exhausted iterator stays on the stack, and the jump
        # lands on END_FOR, which pops it with a placeholder above it
        return 'FOR_ITER_TO_END_FOR', instr.argval
    return instr.opname, instr.argval

@_decodes('END_FOR')
def _decode_end_for(instr, code):
    # END_FOR pops two values on 3.12, one on 3.13+
    return instr.opname, -dis.stack_effect(instr.opcode)

@_decodes('LOAD_DEREF', 'STORE_DEREF', 'DELETE_DEREF', 'LOAD_CLOSURE')
def _decode_free_variable(instr, code):
    # Python 3.11+ numbers these across locals, cells and free variables.
    # RPython functions have no cell variables, so an index into
    # co_freevars means the same on every host.
    return instr.opname, code.co_freevars.index(instr.argval)


@_decodes('CALL_INTRINSIC_1')
def _decode_intrinsic(instr, code):
    return instr.opname, instr.argrepr

def _null_goes_first():
    """Whether the host puts the NULL of a call below the callable (3.11
    and 3.12) or above it (3.13+)."""
    for instr in dis.get_instructions((lambda f: f()).__code__):
        if instr.opname == 'PUSH_NULL':
            return True
        if instr.opname.startswith('LOAD_FAST'):
            return False

if HAS_GET_INSTRUCTIONS:
    NULL_GOES_FIRST = _null_goes_first()

@_decodes('RAISE_VARARGS')
def _decode_raise(instr, code):
    # with two arguments: raise exc from cause, not Python 2's type, value
    return 'RAISE_VARARGS_FROM', instr.arg

@_decodes('LOAD_COMMON_CONSTANT')
def _decode_common_constant(instr, code):
    # the argument indexes a table of constants, which dis keeps privately
    # and names in argrepr
    table = getattr(dis, '_common_constants', None)
    if table is not None:
        return instr.opname, table[instr.arg]
    if instr.argrepr == 'None':
        return instr.opname, None
    return instr.opname, getattr(builtins, instr.argrepr)

@_decodes('LOAD_SPECIAL')
def _decode_load_special(instr, code):
    # the argument indexes a table of special method names, which dis
    # shows as argrepr
    return instr.opname, instr.argrepr

@_decodes('WITH_EXCEPT_START')
def _decode_with_except_start(instr, code):
    # below the exception, the previous exception and lasti: __exit__, and
    # on 3.14, which loads it with LOAD_SPECIAL, its self or NULL
    if 'LOAD_SPECIAL' in opcode.opmap:
        return instr.opname, 4
    return instr.opname, 3

@_decodes('BUILD_MAP')
def _decode_build_map(instr, code):
    # Python 3 pops that many key-value pairs; Python 2 pushes an empty
    # dict of that size and fills it with STORE_MAP
    return 'BUILD_MAP_FROM_ITEMS', instr.arg

@_decodes('MAP_ADD')
def _decode_map_add(instr, code):
    # the key below the value since 3.8, the other way round on Python 2
    return 'MAP_ADD_KEY_VALUE', instr.arg

@_decodes('MAKE_FUNCTION')
def _decode_make_function(instr, code):
    if instr.arg is None:
        # 3.13+: SET_FUNCTION_ATTRIBUTE sets the rest afterwards
        return instr.opname, 0
    # 3.12: the flags of SET_FUNCTION_ATTRIBUTE, all at once; not
    # Python 2's number of defaults
    return 'MAKE_FUNCTION_FLAGS', instr.arg

@_decodes('LOAD_GLOBAL')
def _decode_load_global(instr, code):
    nameindex = code.co_names.index(instr.argval)
    if dis.stack_effect(instr.opcode, instr.arg) == 2:
        # 3.11+ flag bit: push a NULL for CALL as well
        if NULL_GOES_FIRST:
            return 'PUSH_NULL_LOAD_GLOBAL', nameindex
        return 'LOAD_GLOBAL_PUSH_NULL', nameindex
    return instr.opname, nameindex

@_decodes('LOAD_ATTR')
def _decode_load_attr(instr, code):
    nameindex = code.co_names.index(instr.argval)
    if dis.stack_effect(instr.opcode, instr.arg) == 1:
        # 3.12+ flag bit: a method lookup for CALL.  The flow space pushes
        # the bound method and NULL, in the host's order.
        if NULL_GOES_FIRST:
            return 'PUSH_NULL_LOAD_ATTR', nameindex
        return 'LOAD_ATTR_PUSH_NULL', nameindex
    return instr.opname, nameindex


class Instruction(object):
    """A decoded instruction: the handler's name and argument, and what
    the fusing passes need to know about the host instruction."""

    def __init__(self, instr, code):
        self.offset = instr.offset
        self.opname, self.oparg = _normalize(instr, code)
        self.host = instr

    def stack_effect(self):
        return dis.stack_effect(self.host.opcode, self.host.arg)

    def is_host(self, opname, arg=None):
        return (self.host.opname == opname and
                (arg is None or self.host.arg == arg))

    def replace(self, opname, oparg=0):
        self.opname = opname
        self.oparg = oparg


def _operands_start(instrs, index, count, jump_targets):
    """Index of the first instruction computing the 'count' values that
    instrs[index] consumes, or None if they are not straight-line code."""
    depth = 0
    i = index
    while depth < count:
        i -= 1
        if i < 0:
            return None
        instr = instrs[i]
        if instr.host.opcode in JUMP_OPCODES or instr.offset in jump_targets:
            return None
        depth += instr.stack_effect()
    if depth != count:
        return None
    return i


# Python 3.12+ compiles del x[a:b], and 3.14 also x[a:b], to a
# BUILD_SLICE that the next instruction consumes.  RPython has no slice
# objects, so the pair decodes as the slice operation of Python 2.
_SLICE_OPERATIONS = {
    ('BINARY_SUBSCR', 0): 'SLICE_3',
    ('BINARY_OP', '[]'): 'SLICE_3',
    ('STORE_SUBSCR', 0): 'STORE_SLICE_3',
    ('DELETE_SUBSCR', 0): 'DELETE_SLICE_3',
}

def _fuse_slice(instrs, i, jump_targets):
    instr = instrs[i]
    if instr.is_host('BUILD_SLICE', 2) and i + 1 < len(instrs):
        following = instrs[i + 1]
        opname = _SLICE_OPERATIONS.get((following.opname, following.oparg))
        if opname is not None:
            instr.replace('NOP')
            following.replace(opname)

def _fuse_constant_list(instrs, i, jump_targets):
    # [1, 2, 3] is BUILD_LIST 0, LOAD_CONST (1, 2, 3), LIST_EXTEND 1
    if (instrs[i].is_host('LIST_EXTEND', 1) and i >= 2 and
            instrs[i - 1].is_host('LOAD_CONST') and
            instrs[i - 2].is_host('BUILD_LIST', 0) and
            instrs[i - 1].offset not in jump_targets and
            instrs[i].offset not in jump_targets):
        instrs[i].replace('BUILD_LIST_FROM_CONST', instrs[i - 1].oparg)
        instrs[i - 1].replace('NOP')
        instrs[i - 2].replace('NOP')

def _fuse_keyword_names(instrs, i, jump_targets):
    # 3.12: KW_NAMES sets the keyword names of the CALL that follows it.
    # Load them instead, which is how CALL_KW of 3.13+ expects them.
    instr = instrs[i]
    if instr.is_host('KW_NAMES'):
        instr.replace('LOAD_CONST', instr.oparg)
        assert instrs[i + 1].opname == 'CALL'
        instrs[i + 1].replace('CALL_KW', instrs[i + 1].oparg)

def _fuse_star_call(instrs, i, jump_targets):
    """f(a, *args, k=v) builds a list, extends it with args, converts it
    to a tuple, builds a dict of the keywords and calls
    CALL_FUNCTION_EX.  RPython has a fixed number of arguments and
    keywords, so the builders become NOPs that leave the values on the
    stack, and CALL_FUNCTION_EX gets their number:
    (positional count, keyword count or None, whether there is a
    keyword slot).  Anything else stays as it is, and fails where the
    handlers find a list or dict that they cannot unpack.
    """
    call = instrs[i]
    if not call.is_host('CALL_FUNCTION_EX'):
        return
    # the callable, NULL or self, the arguments and on 3.14 or with
    # keywords, their dict or NULL
    has_kwslot = 1 - call.stack_effect() == 4
    n_keywords = None
    star_end = i - 1
    if has_kwslot:
        builder = instrs[i - 1]
        if builder.is_host('BUILD_MAP') and builder.offset not in jump_targets:
            start = _operands_start(instrs, i - 1, 2 * builder.oparg,
                                    jump_targets)
            if start is not None:
                n_keywords = builder.oparg
                builder.replace('NOP')
                star_end = start - 1
        else:
            start = _operands_start(instrs, i, 1, jump_targets)
            if start is None:
                return
            star_end = start - 1
    n_positional = 0
    if (star_end >= 1 and
            instrs[star_end].is_host('CALL_INTRINSIC_1') and
            instrs[star_end].host.argrepr == 'INTRINSIC_LIST_TO_TUPLE' and
            instrs[star_end - 1].is_host('LIST_EXTEND', 1)):
        extend = star_end - 1
        start = _operands_start(instrs, extend, 1, jump_targets)
        if (start is not None and start >= 1 and
                instrs[start - 1].is_host('BUILD_LIST') and
                instrs[start].offset not in jump_targets):
            n_positional = instrs[start - 1].oparg
            for j in (start - 1, extend, star_end):
                instrs[j].replace('NOP')
    call.replace('CALL_FUNCTION_EX', (n_positional, n_keywords, has_kwslot))

_FUSING_PASSES = [_fuse_slice, _fuse_constant_list, _fuse_keyword_names,
                  _fuse_star_call]


def decode_instructions(code):
    """Decode a host code object with the dis module (Python 3 hosts).

    Returns ({offset: (next_offset, opname, oparg)}, exception_entries).
    dis resolves what differs between bytecode versions: EXTENDED_ARG,
    inline cache entries and the unit and direction of jumps.  The
    exception entries are (start, end, target, depth, lasti) tuples, with
    'end' exclusive, from the exception table of CPython 3.11 and later.
    """
    instrs = []
    prefixes = {}     # EXTENDED_ARG offset -> offset of its instruction
    pending = []
    for instr in dis.get_instructions(code):
        if instr.opname == 'EXTENDED_ARG':
            # dis already folded the prefix into the argument of the
            # instruction that follows; jumps may still target the prefix
            pending.append(instr.offset)
            continue
        for offset in pending:
            prefixes[offset] = instr.offset
        pending = []
        instrs.append(Instruction(instr, code))
    bytecode = dis.Bytecode(code)
    exception_entries = tuple(
        (entry.start, entry.end, entry.target, entry.depth, entry.lasti)
        for entry in getattr(bytecode, 'exception_entries', ()))
    jump_targets = set(instr.oparg for instr in instrs
                       if instr.host.opcode in JUMP_OPCODES)
    jump_targets.update(entry[2] for entry in exception_entries)
    jump_targets = set(prefixes.get(target, target)
                       for target in jump_targets)
    for fuse in _FUSING_PASSES:
        for i in range(len(instrs)):
            fuse(instrs, i, jump_targets)
    table = {}
    for i, instr in enumerate(instrs):
        if i + 1 < len(instrs):
            next_offset = instrs[i + 1].offset
        else:
            next_offset = len(code.co_code)
        table[instr.offset] = (next_offset, instr.opname, instr.oparg)
    for prefix, offset in prefixes.items():
        table[prefix] = table[offset]
    return table, exception_entries


_CLEANUP_OPNAMES = frozenset(['NOP', 'COPY', 'SWAP', 'POP_TOP', 'POP_EXCEPT',
                              'LOAD_CONST', 'STORE_FAST', 'DELETE_FAST'])


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

    def exception_handler(self, offset):
        """The exception table entry that handles an exception at offset"""
        for entry in self.exception_entries:
            start, end = entry[0], entry[1]
            if start <= offset < end:
                return entry
        return None

    def catches(self, offset):
        """Whether an exception at offset reaches an exception table
        handler that does more than clean up and re-raise it.

        Python 3.11+ cleans up after comprehensions and 'except ... as'
        in handlers of their own.  Counting those would make the flow
        space catch implicit exceptions that Python 2 hosts do not.
        """
        entry = self.exception_handler(offset)
        if entry is None:
            return False
        reraise = self._cleanup_reraise(entry[2])
        if reraise is None:
            return True
        return self.catches(reraise)

    def _cleanup_reraise(self, offset):
        """The offset of the RERAISE ending the handler at offset, if the
        handler does nothing else than clean up"""
        while True:
            next_offset, opname, _ = self.read(offset)
            if opname == 'RERAISE':
                return offset
            if opname not in _CLEANUP_OPNAMES:
                return None
            offset = next_offset

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
