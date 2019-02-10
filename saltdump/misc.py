# coding: utf-8

class Attr(object):
    def __init__(self, **kw):
        for k,v in kw.iteritems():
            if hasattr(self, k):
                raise Exception('attr "{0}" is taken'.format(k))
            setattr(self, k, v)

    def __repr__(self):
        return str(self.__dict__)
    __str__ = __repr__
