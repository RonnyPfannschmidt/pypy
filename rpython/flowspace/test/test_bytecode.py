import opcode

from rpython.flowspace.bytecode import HostCode
from rpython.tool.error import offset2lineno

JUMPS = set(opcode.opname[i] for i in opcode.hasjrel + opcode.hasjabs)


def decode(func):
    code = HostCode._from_code(func.__code__)
    offset = 0
    result = []
    while offset < len(code.co_code):
        next_offset, opname, oparg = code.read(offset)
        assert next_offset > offset
        result.append((offset, opname, oparg))
        offset = next_offset
    return result


def loop(xs):
    total = 0
    for x in xs:
        if x:
            continue
        total += 1
    return total


def test_read_ends_at_return():
    instrs = decode(loop)
    assert instrs[-1][1] in ('RETURN_VALUE', 'RETURN_CONST')


def test_jump_targets_are_instruction_offsets():
    instrs = decode(loop)
    offsets = set(offset for offset, _, _ in instrs)
    jumps = [(opname, oparg) for _, opname, oparg in instrs if opname in JUMPS]
    assert jumps
    for opname, target in jumps:
        assert target in offsets, (opname, target)


def test_extended_arg_is_folded_into_the_argument():
    source = "def f():\n" + "".join(
        "    x = %d.5\n" % i for i in range(300)) + "    return x\n"
    namespace = {}
    exec(source, namespace)
    instrs = decode(namespace['f'])
    assert 'EXTENDED_ARG' not in [opname for _, opname, _ in instrs]
    assert max(oparg for _, opname, oparg in instrs
               if opname == 'LOAD_CONST') > 255


def test_offset2lineno():
    code = loop.__code__
    last_offset = decode(loop)[-1][0]
    assert offset2lineno(code, last_offset) == code.co_firstlineno + 6
