from __future__ import print_function

import random

import pytest

from rpython.translator.c.support import gen_assignments


@pytest.mark.parametrize('input', [
    [('int @', 'a', 'a')],
    [('int @', 'a', 'b')],
    [('int @', 'a', 'b'),
     ('int @', 'c', 'b')],
    [('int @', 'a', 'b'),
     ('int @', 'b', 'c')],
    [('int @', 'b', 'c'),
     ('int @', 'a', 'b')],
    [('int @', 'a', 'b'),
     ('int @', 'b', 'a')],
    [('int @', 'a', 'b'),
     ('int @', 'b', 'c'),
     ('int @', 'd', 'b')],
])
def test_gen_simple_assignments(input):
    gen_check(input)

def gen_check(input):
    for _, dst, src in input:
        print('input:', dst, src)
    result = ' '.join(gen_assignments(input))
    print(result)
    result = result.replace('{ int', '').replace('}', '').strip()
    d = {}
    for _, dst, src in input:
        d[src] = '<value of %s>' % (src,)
    exec(result, d)
    for _, dst, src in input:
        assert d[dst] == '<value of %s>' % (src,)

@pytest.mark.parametrize('i', range(100))
def test_gen_check(i):
    varlist = list('abcdefg')
    random.shuffle(varlist)
    input = [('int @', varlist[n], random.choice(varlist))
             for n in range(random.randrange(1, 7))]
    gen_check(input)
