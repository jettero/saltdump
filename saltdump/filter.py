# coding: utf-8

from __future__ import print_function

import re
import lark
import logging
import fnmatch

log = logging.getLogger(__name__)

class Match(object):
    notted = False

    def __init__(self, match):
        self.match = match

    def __call__(self, text):
        if self.notted:
            return not fnmatch.fnmatch(text, self.match)
        return fnmatch.fnmatch(text, self.match)

    def __repr__(self):
        if self.notted:
            return "¡{0}!".format(self.match)
        return "/{0}/".format(self.match)

class AndOp(object):
    def __init__(self, *args):
        self.args = args

    def __call__(self, v):
        for a in self.args:
            if not a(v):
                return False
        return True

    def __repr__(self):
        sep = ' {0} '.format(self.__class__.__name__)
        return '[{0}]'.format( sep.join([ str(v) for v in self.args ]) )

class OrOp(AndOp):
    def __call__(self, v):
        for a in self.args:
            if a(v):
                return True
        return False

class FilterTransformer(object):
    @lark.v_args(inline=True)
    def expr(self, *elist):
        log.debug(' FilterTransformer.expr( %s )', elist)
        if len(elist) == 1:
            if isinstance(elist[0], lark.Token):
                return Match(elist[0])
            return elist[0]
        if len(elist) == 3:
            ex1, bop, ex2 = elist
            return AndOp(ex1, ex2) if bop == 'and' else OrOp(ex1, ex2)
        if len(elist) == 2:
            urop, exp = elist
            if urop == 'not':
                exp.notted = not exp.notted
            return exp
        raise Exception('XXX')

GRAMMAR = r'''
%import common.WS
%ignore WS

URN_OP: "not"
BIN_OP: "or" | "and"
WORD: /[^"()\s]+/
INNER: "\\\"" | WS | WORD
STRING: "\"" INNER* "\""
MATCH: WORD | STRING

expr: MATCH | URN_OP expr | expr BIN_OP expr  | "(" expr ")"

?start: expr
'''

Parser = lark.Lark(GRAMMAR, parser='lalr', transformer=FilterTransformer())

class AlwaysTrue(object):
    def __call__(self):
        return True

def build_filter(*x):
    x = ' '.join(x)
    log.debug('parsing filter="%s"', x)
    if not x:
        log.debug(' nothing to parse, returning lambda *a: True')
        return lambda *a: True
    if isinstance(x, (list,tuple)):
        x = ' '.join(x)
    x = Parser.parse(x)
    log.debug(' result: %s', x)
    return x
