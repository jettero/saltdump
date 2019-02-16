# coding: utf-8

import time, os, re
import dateutil.parser, dateutil.tz
import datetime

class Attr(object):
    def __init__(self, **kw):
        for k,v in kw.iteritems():
            if hasattr(self, k):
                raise Exception('attr "{0}" is taken'.format(k))
            setattr(self, k, v)

    def __repr__(self):
        return str(self.__dict__)
    __str__ = __repr__

tzinfos = dict()
def build_tzinfos(load_re='^...$|^US/'):
    r = re.compile(load_re.strip())

    from . import _common_tz
    for i in _common_tz.common_timezones:
        # NOTE: this probably isn't super reliable for various reasons:
        # 1) these abbreviations are notoriously ambiguous
        # 2) I'm using tzinfo._trans_idx (clearly meant to be a secret)
        # 3) why do I only look at the last 10 transitions? why not the last 30?
        # 4) ... or the last 2? seems kinda arbitrary, neh?
        # ?) other things I'm not thinking of
        # It does have the benefit of being rather simple though.
        if r.search(i):
            tzinfo = dateutil.tz.gettz(i)
            tranil = dict([ (x.abbr,tzinfo) for x in tzinfo._trans_idx[-10:] ])
            tzinfos.update(tranil)

build_tzinfos()
del build_tzinfos

class DateParser:
    def __init__(self, date_string, fmt='%Y-%m-%d %H:%M:%S %Z/%z', guess_tz=os.environ.get('TZ','UTC')):
        if not date_string or date_string == 'now':
            self.orig = datetime.datetime.now().isoformat()
        else:
            self.orig = date_string
        del date_string
        self.parsed = dateutil.parser.parse(self.orig, tzinfos=tzinfos)
        if self.parsed.tzinfo is None:
            self.parsed = self.parsed.replace(tzinfo=dateutil.tz.gettz())
        self.tstamp = time.mktime(self.parsed.timetuple())
        self.fmt    = self.parsed.strftime(fmt)
