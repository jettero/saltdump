# coding: utf-8

import logging, copy
import json, inspect, re
from fnmatch import fnmatch
from collections import OrderedDict

import salt.output

from .structured import StructuredMixin
from .config import SaltConfigMixin
from .misc import DateParser

SHOW_JIDS = False

NA = '<n/a>'
tagtop_re = re.compile(r'^\s*([^\s{}:]+)\s*{')

REFORMAT_IDS = lambda x: x

log = logging.getLogger(__name__)

def reformat_minion_ids(matchers):
    def _m(minion_id):
        for matcher in matchers:
            if matcher.match(minion_id):
                log.debug("matcher=%s matched id=%s", matcher, minion_id)
                minion_id = '.'.join(matcher.groups())
                log.debug("        reformatted id=%s", minion_id)
        return minion_id
    global REFORMAT_IDS
    REFORMAT_IDS = _m

class Job(SaltConfigMixin, StructuredMixin):
    def __init__(self, jid):
        self.jid       = jid
        self.events    = []
        self.expected  = set()
        self.returned  = set()
        self.listeners = []
        self.find_jobs = {}

        self.ptime = DateParser('now')
        self.stamp = self.ptime.orig
        self.dtime = self.ptime.parsed
        self.itime = self.ptime.tstamp

    @property
    def all_events(self):
        # shallow copy so we're talking about the same events
        # but we don't dick up the self.events when we extend()
        ev = copy.copy(self.events)
        for evl in self.find_jobs.values():
            ev.extend(evl)
        return sorted(ev, key=lambda x: x.jid)

    def append(self, event):
        if isinstance(event, (FindJobPub,FindJobRet)):
            if event.jid not in self.find_jobs:
                self.find_jobs[ event.jid ] = []
            self.find_jobs[ event.jid ].append( event )
            return

        if event.dtime and (not self.dtime or self.dtime < event.dtime):
            self.dtime = event.dtime
        self.events.append(event)

    def subsume(self, jitem):
        new_ev = [ ev for ev in jitem.events if ev not in self.events ]
        self.events.extend(new_ev)

    @property
    def event_count(self):
        return len(self.all_events)

    @property
    def returned_count(self):
        return (len(self.returned),len(self.expected))

    @property
    def rc_count(self):
        c = t = 0
        for event in self.events:
            if hasattr(event,'rc_ok'):
                t += 1
                if event.rc_ok:
                    c += 1
        if t:
            return (c,t)

    @property
    def find_count(self):
        log.debug('find_count() jids in find: %s', self.find_jobs.keys())
        p = 0
        for i in self.find_jobs.values():
            p += 1
            # XXX we could say whether the ayt worked and by what percent …
        return p

    @property
    def find_detail(self):
        ret = {}
        for jid in sorted(self.find_jobs):
            for j in self.find_jobs[jid]:
                if isinstance(j, (FindJobPub,ExpectedReturns)):
                    for e in j.minions:
                        if e not in ret:
                            ret[e] = 'ayt'
                elif isinstance(j,FindJobRet):
                    if j.id in ret:
                        del ret[j.id]
        return ret

    @property
    def return_detail(self):
        ret = {}
        for ev in self.events:
            if isinstance(ev,Return):
                ret[ev.id] = ev
        return ret

    @property
    def job_detail(self):
        wait = self.waiting
        hosts = wait.union( self.returned )
        findr = self.find_detail
        retns = self.return_detail

        ret = []
        for host in sorted(hosts):
            statuses = set()
            if host in wait:
                statuses.add('waiting')
            elif host in retns:
                r = retns[host]
                if hasattr(r, 'rc_ok'):
                    statuses.add('rc_ok' if r.rc_ok else 'rc_bad')
                if hasattr(r, 'changes_count') and r.changes_count > 0:
                    statuses.add('changes')
            if host in findr:
                statuses.add('ayt')
            ret.append( (host,) + tuple(statuses) )
        return ret

    @property
    def job_desc(self):
        p_ev = [ x for x in self.events if isinstance(x,Publish) and not isinstance(x,FindJobPub) ]
        if p_ev:
            if len(p_ev) > 1:
                log.info("jid=%s has more than one Publish", self.jid)
                for p in p_ev:
                    log.info(" - %s", p.what)
            return p_ev[0].job_desc
        log.info("jid=%s has no Publish", self.jid)
        r_ev = [ x for x in self.events if isinstance(x,Return) ]
        if r_ev:
            if len(r_ev) > 1:
                log.debug("jid=%s has more than one Return", self.jid)
                for r in r_ev:
                    log.debug(" - %s", r.what)
            return r_ev[0].job_desc
        return ('','','')

    @property
    def columns(self):
        c = [ self.tag ]
        c.append( u'ev={0}'.format( self.event_count ) )

        f = self.find_count
        c.append( u'ayt={0}'.format(f) if f else '' )

        c.append( u'ret={0}/{1}'.format( *self.returned_count ) )

        s = self.rc_count
        c.append( u'good={0}/{1}'.format(*s) if s else '' )

        c.extend( self.job_desc )

        return c

    @property
    def raw(self):
        dat = dict(_stamp=self.stamp)
        ret = dict(tag=self.tag, data=dat)
        for fname in ('event_count', 'find_count', 'returned_count', 'rc_count', 'job_desc'):
            v = getattr(self, fname)
            if isinstance(v, (list,tuple)):
                v = '/'.join(tuple( str(x) for x in v ))
            dat[ fname ] = v
        return ret

    @property
    def tag(self):
        return 'saltdump/job/{0}/info'.format(self.jid)

    @property
    def short(self):
        return u' '.join(tuple( x for x in self.columns if x ))

    def json(self, indent=2):
        kw = dict()
        if indent:
            kw['indent'] = indent
        return json.dumps(self.raw, **kw)

    @property
    def waiting(self):
        return self.expected - self.returned

class JidCollector(object):
    def __init__(self, max_jobs=50):
        self.jids = {}
        self.listeners = []
        self.max_jobs  = max_jobs

        # XXX: if we ever get to the point of cleaning up jids from self.jids,
        # we'll have to remember to clean them from this too
        self.map_jids = {}

    def set_max_jobs(self, mj):
        oj = self.max_jobs
        self.max_jobs = mj
        # XXX: we should immediately reduce the list here if this number goes down

    def on_change(self, callback):
        if callback not in self.listeners:
            self.listeners.append(callback)

    def examine_event(self, event):
        if not isinstance(event,Event):
            try: event = classify_event(event)
            except: return

        actions = set()

        if hasattr(event,'jid'):
            if hasattr(event,'fjid'):
                self.map_jids[ event.jid ] = event.fjid
            actual_jid = self.map_jids.get(event.jid, event.jid)

            if actual_jid in self.jids:
                jitem = self.jids[ actual_jid ]
            else:
                jitem = Job(actual_jid)
                self.jids[ actual_jid ] = jitem
                actions.add('new-jid')

            jitem.append(event)
            actions.add('append-event')

            if event.jid in jitem.find_jobs:
                actions.add('find-job')
                log.debug("considering subsuming jid=%s", event.jid)
                if event.jid in self.jids:
                    log.debug(" subsuming jitem=%s", self.jids[event.jid])
                    jitem.subsume( self.jids.pop( event.jid ) )
                    actions.add('subsume-jitem-%s', event.jid)
                else:
                    log.debug(" not subsuming jid=%s", event.jid)

            elif isinstance(event, ExpectedReturns):
                for m in event.minions:
                    if m not in jitem.expected:
                        actions.add('add-expected')
                        jitem.expected.add(m)

            elif isinstance(event, Return):
                if event.id in jitem.expected:
                    if event.id not in jitem.returned:
                        actions.add('add-returned')
                        jitem.returned.add(event.id)

            if len(self.jids) > self.max_jobs:
                to_kill = sorted( self.jids.keys() )[0:( len(self.jids) - self.max_jobs )]
                for i in to_kill:
                    del self.jids[i]
                    actions.add('expire-jitem-{0}'.format(i))
                m_to_kill = [ k for k in self.map_jids if self.map_jids[k] in to_kill ]
                for i in m_to_kill:
                    del self.map_jids[i]

            if actions:
                for l in self.listeners:
                    l(jitem, tuple(actions))

            log.debug("examine-event event.jid=%s actual_jid=%s tracked_jids=%s",
                repr(event.jid), repr(actual_jid), repr(self.jids.keys()) )
        else:
            log.debug("examine-event finds no jid here: %s", event)

    @property
    def waiting(self):
        ret = {}
        for jid,dat in self.jids.iteritems():
            if dat.waiting:
                ret[jid] = dat
        return ret

    def __repr__(self):
        ret = "jidcollection:\n"
        for jid,jitem in self.jids.iteritems():
            ret += ' - {jid} dtime={jitem.dtime} returned={jitem.returned} expected={jitem.expected}\n'.format(
                jid=jid, jitem=jitem)
        return ret

def grok_json_event(json_data):
    if isinstance(json_data, dict):
        return json_data

    m = tagtop_re.search(json_data)
    if m:
        tagtop = m.group(1)
        json_data = tagtop_re.sub('{', json_data)
    else:
        tagtop = None

    json_data = json.loads(json_data)
    if tagtop:
        json_data = { 'tag': tagtop, 'data': json_data }
    return json_data

def _count_bases(x, classes):
    if x not in classes:
        return 0
    if not x._ordering:
        c = 1
        for b in x.__bases__:
            if b in classes:
                c += _count_bases(b, classes)
        x._ordering = c
    return x._ordering

def event_classes():
    # attempt to impose an orderin on the classes, such that a subclass of a
    # class is tried before the class while matching classes
    classes = []
    for cls in globals().values():
        if inspect.isclass(cls) and issubclass(cls, Event):
            cls._ordering = 0
            classes.append(cls)
    classes = sorted([ (_count_bases(x,classes),x) for x in classes ])
    classes.reverse()
    return [ x[1] for x in classes ]

def classify_event(json_data):
    if isinstance(json_data, Event):
        return json_data
    raw = grok_json_event(json_data)
    for cls in event_classes():
        if cls.match(raw):
            # noisy
            # log.debug('classifying %s as %s', raw, cls)
            return cls(raw)
    return Event(raw)

def my_args_format(x):
    if not x or x is NA or x == NA:
        return ''
    if not isinstance(x, (list,tuple)):
        return json.dumps(x)

    ret = []
    for i in x:
        if isinstance(i,dict):
            for k,v in i.iteritems():
                ret.append(u'{0}={1}'.format(k,v))
        elif not i or i is NA or i == NA:
            ret.append(u'')
        else:
            ret.append(unicode(i))
    for i,v in enumerate(ret):
        if u' ' in v:
            ret[i] = u'«{0}»'.format(v)
    return u' '.join(ret)

def my_jid_format(jid):
    try:
        jid = str(jid)
        if len(jid) != 20:
            return ''
        year = jid[:4]
        month = jid[4:6]
        day = jid[6:8]
        hour = jid[8:10]
        minute = jid[10:12]
        second = jid[12:14]
        micro = jid[14:]
        return '{0}-{1}-{2} {3}:{4}:{5}.{6}'.format( year,month,day,hour,minute,second,micro )
    except:
        return jid

class Event(SaltConfigMixin, StructuredMixin):
    matches = ()

    def __init__(self, raw):
        self.raw = raw
        self.tag = self.raw.get('tag', NA)
        self.dat = self.raw.get('data', {})

        # This is meant to descend into minion returns to syndic returns to
        # master.  It's not totally obvious when to go into data={'data': {}},
        # but this rule seems to be right most of the time.
        while 'data' in self.dat and isinstance(self.dat['data'],dict) and 'id' in self.dat['data']:
            self.dat = self.dat['data']

        self.stamp = self.dat.get('_stamp')
        self.ptime = DateParser(self.stamp)
        self.dtime = self.ptime.parsed
        self.itime = self.ptime.tstamp

    def __reduce__(self):
        return (self.__class__, (self.raw,))

    def json(self, indent=2):
        kw = dict()
        if indent:
            kw['indent'] = indent
        return json.dumps(self.raw, **kw)

    def outputter(self, **kw):
        return self.short

    @classmethod
    def match(cls, raw):
        ''' class matching method for pairing up event data with object type

            All classname.matches must be tuples or lists.
                class ExampleThing(Event):
                    matches = (
                        ('tag', 'salt/job/*/ret/*'),
                        ('fun', 'state.sls'),
                    )

            match element formats:
              Find 'key' in event data (slogging through data: { 'data': ... } and other places to find it)
                ('key', 'string')

              All simple string matches are passed through fnmatch.fnmatch() for globbiness
                ('key', 'string*')

              For regular expressiong matching, pre-compile the match
                ('key', re.compile(r'string.*'))

              Key lookup values can also be a tuple of _OR_ items
                ('key', ('blah1*', 'blah2*', re.compile(r'things')))
                in which case, either blah1 or blah2 match will do the trick

            top level matches are _AND_ed so all must match or there is no match.

              example.matches = (
                ('tag', ('blah/*', 'blarg/*')),
                ('fun', ('state.sls', 'state.highstate')),
              )

              In this example, in order to match, the tag must be either
              (blah/something or blarg/something) and the fun must be either
              (state.sls or state.highstate) or there is no match.

            Classes are matched in order of inheritence depth.

                class Event(...)
                class SendEvent(Event)
                class Return(Event)
                class SpecificReturn(Return)
                class EventMoreSpecificReturn(SpecificReturn)

                The the matcher would try hardest to match EvenMoreSpecificReturn, trying SpecificReturn next,
                only checking Event as the very last set of checks.

        '''
        if not hasattr(cls,'matches') or not cls.matches:
            return False
        for key,pats in cls.matches:
            if not isinstance(pats,(list,tuple)):
                pats = (pats,)

            _find = raw
            tstr = _find.get(key)
            while tstr is None and 'data' in _find:
                _find = _find['data']
                tstr = _find.get(key)
            if tstr is None:
                return False

            p_matched = False
            for pat in pats:
                if isinstance(pat,str):
                    if fnmatch(tstr, pat):
                        p_matched = True
                        break
                elif pat.match(tstr):
                    p_matched = True
                    break

            if not p_matched:
                return False

        return True

    def has_tag(self, pat):
        return self._glob(self.tag, pat)

    def try_attr(self, attr, default=NA, no_none=False, preformat=None):
        ret = default
        if not isinstance(attr, (list,tuple)):
            attr = (attr,)
        for a in attr:
            if hasattr(self,a):
                ret = getattr(self,a)
                break;
            elif a in self.dat:
                ret = self.dat[a]
                break;
            elif a in self.raw:
                ret = self.raw[a]
                break;
        if no_none and ret is None:
            ret = default
        if preformat and (not isinstance(ret, (str,unicode)) or ret == NA):
            ret = preformat(ret)
        return ret

    @property
    def who(self):
        return REFORMAT_IDS( self.try_attr('id') )

    @property
    def what(self):
        fun = self.try_attr('fun')
        if fun != '<n/a>':
            return (fun, self.try_attr('fun_args', preformat=my_args_format), )
        return (self.try_attr('tag'),)

    def __iter__(self):
        for item in [ self.__class__.__name__, self.who, self.what ]:
            if isinstance(item, (list,tuple)):
                yield u' '.join(item)
                continue
            yield item

    @property
    def columns(self):
        return tuple( '' if x == '<n/a>' else x for x in self )

    @property
    def jcolumns(self):
        return (getattr(self, 'jid', ''),) + self.columns

    @property
    def tcolumns(self):
        return (getattr(self, 'tag', ''),) + self.columns

    @property
    def short(self):
        return u' '.join(tuple( x for x in self.tcolumns if x ))

    def __repr__(self):
        return self.short
    __str__ = __repr__


class Auth(Event):
    matches = (( 'tag', 'salt/auth' ),)

    def __init__(self, *args, **kwargs):
        super(Auth,self).__init__(*args,**kwargs)
        self.result = self.dat.get('result', False)
        self.id     = self.dat.get('id', NA)
        self.act    = self.dat.get('act', NA)

    @property
    def structured(self):
        stru = super(Auth, self).structured
        pkey = stru.get('data', {}).get('pub')
        if "PUBLIC KEY" in pkey:
            fake_finger = ''
            for line in pkey.splitlines()[1:-1]:
                fake_finger += line[0:2] + line[-2:]
            stru['data']['pub'] = ''.join(sorted(fake_finger))
        return stru

    @property
    def what(self):
        v = self.try_attr('act')
        if v == 'accept':
            v = u"{0} → {1}".format(v, self.try_attr('result') )
        return v

class JobEvent(Event):
    def __init__(self, *args, **kwargs):
        super(JobEvent,self).__init__(*args,**kwargs)
        self.jid      = self.dat.get('jid', NA)
        self.fun      = self.dat.get('fun', NA)
        self.tgt      = self.dat.get('tgt', NA)
        self.tgt_type = self.dat.get('tgt_type', NA)

        self.args = self.try_attr( ('arg','args','fun_args',), [] )

        asr = [ ]
        if self.args:
            for x in self.args:
                if isinstance(x,dict):
                    for k,v in x.iteritems():
                        asr.append('{0}={1}'.format(k,v))
                else:
                    asr.append(str(x))
        self.args_str = ' '.join(asr)

class DataCacheRefresh(Event):
    matches = (( 'tag', 'minion/refresh/*' ),)

    @property
    def structured(self):
        stru = super(DataCacheRefresh, self).structured
        mid = stru['minion_id'] = stru['src_host'] = self.tag.split('/')[-1]
        stru['short_path'] = stru['short_path'].replace('/' + mid, '')
        return stru

class ExpectedReturns(Event):
    matches = (( 'tag', re.compile(r'\d+') ),)
    who = 'local'

    def __init__(self, *args, **kwargs):
        super(ExpectedReturns,self).__init__(*args,**kwargs)
        self.minions = self.dat.get('minions', [])
        self.jid = self.tag.strip()

    @property
    def what(self):
        return ', '.join(self.minions)

class SyndicExpectedReturns(ExpectedReturns):
    matches = (('tag',re.compile(r'syndic/[^/]+/\d+')),)
    who = ''

    def __init__(self, *args, **kwargs):
        super(SyndicExpectedReturns,self).__init__(*args,**kwargs)
        self.syndic = self.tag.split('/')[1]
        self.who = self.syndic

class Publish(JobEvent):
    matches = (('tag', 'salt/job/*/new'),)
    who = ''

    def __init__(self, *args, **kwargs):
        super(Publish,self).__init__(*args,**kwargs)
        self.user    = self.dat.get('user', NA)
        self.minions = self.dat.get('minions', [])
        self.who     = self.dat.get('user', 'local')
        if self.who.startswith('sudo_'):
            self.who = self.who[5:]
        if not self.who or self.who == 'root':
            self.who = 'local'

    @property
    def job_desc(self):
        tgt = self.try_attr('tgt')
        tgt_type = self.try_attr('tgt_type')

	# this is cut and pasted from salt/minion.py:Matcher.compound_match
        # it doesn't seem to be defined anywhere else
        # then I reversed it, ... der.
        # ref = {'G': 'grain',
        #        'P': 'grain_pcre',
        #        'I': 'pillar',
        #        'J': 'pillar_pcre',
        #        'L': 'list',
        #        'N': None,      # Nodegroups should already be expanded
        #        'S': 'ipcidr',
        #        'E': 'pcre'}

        unref = {
            'grain':        'G',
            'grain_pcre':   'P',
            'pillar':       'I',
            'pillar_pcre':  'J',
            'list':         'L',
            'ipcidr':       'S',
            'pcre':         'E',
            'glob':         None
        }

        if isinstance(tgt,(list,tuple)):
            tgt = u','.join(tgt)

        if tgt_type in unref:
            if unref[tgt_type] is not None:
                tv = u'{0}@{1}'.format(unref[tgt_type],tgt)
            else:
                tv = u'{0}'.format(tgt)
        else:
            tv = '<{0}>@{1}'.format( self.try_attr('tgt_type'), self.try_attr('tgt') )

        return (
            tv,
            self.try_attr('fun'),
            self.try_attr('arg', preformat=my_args_format),
        )

    @property
    def what(self):
        jd = self.job_desc
        return u'{target} {fun} {fun_args}'.format(
            target=jd[0], fun=jd[1], fun_args=jd[2]
        )

class Return(JobEvent):
    matches = (('tag', 'salt/job/*/ret/*'),)
    ooverrides = {}

    def __init__(self, *args, **kwargs):
        super(Return,self).__init__(*args,**kwargs)
        self.success = self.dat.get('success', NA)
        self.retcode = self.dat.get('retcode', 0)
        self.returnd = self.dat.get('return', 0)
        self.id      = self.dat.get('id', NA)

        self.rc_ok = False
        try:
            if int( self.retcode ) == 0:
                self.rc_ok = True
        except:
            pass

    def outputter(self, outputter=None, default_outputter='nested', **kw):
        dat = self.raw.get('data', {})
        dat_outputter = dat.get('out')
        picked_outputter = outputter or dat_outputter or default_outputter
        log.debug('%s.outputter using outputter=%s or dat_outputter=%s or default_outputter=%s ---> %s',
            self.__class__.__name__,
            outputter, dat_outputter, default_outputter, picked_outputter)
        return_data = copy.deepcopy( dat.get('return', dat) )
        to_output = { dat.get('id', 'local'): return_data }
        if picked_outputter:
            log.debug('trying to apply outputter=%s', picked_outputter)
            over = dict(**self.ooverrides)
            over.update(kw)
            res = salt.output.out_format(to_output, picked_outputter, self.salt_opts, **over)
            log.debug('outputter put out %d bytes', len(res))
            if res:
                ret = [
                    '## ' + self.short,
                    res.rstrip()
                ]
                return '\n'.join(ret)
        return self.short

    @property
    def job_desc(self):
        return (
            '<{0}>'.format(self.try_attr('id')),
            self.try_attr('fun'),
            self.try_attr('fun_args', preformat=my_args_format),
        )

class StateReturn(Return):
    matches = Return.matches + (
        ('fun', ('state.sls','state.highstate','state.apply')),
    )

    def __init__(self, *a, **kw):
        super(StateReturn,self).__init__(*a,**kw)
        self.changes = {}
        self.results = {}

        self.changes_count = 0
        self.result_counts = [0,0]

        if isinstance(self.returnd, dict):
            for v in self.returnd.values():
                if '__id__' in v:
                    if 'changes' in v and isinstance(v['changes'],dict):
                        self.changes[ v['__id__'] ] = v['changes']
                        if v['changes']:
                            self.changes_count += 1
                    if 'result' in v:
                        self.results[ v['__id__'] ] = bool(v['result'])
                        self.result_counts[1] += 1
                        if v['result']:
                            self.result_counts[0] += 1

    @property
    def what(self):
        w = super(StateReturn,self).what
        m = 'changes={0} success={1}/{2}'.format( self.changes_count, *self.result_counts )
        if isinstance(w,(list,tuple)):
            return w + (m,)
        return '{0} {1}'.format(w,m)

class PublishRun(JobEvent):
    matches = (('tag', 'salt/run/*/new'),)

    def __init__(self, *args, **kwargs):
        super(PublishRun,self).__init__(*args,**kwargs)
        self.user = self.dat.get('user', NA)

class RunReturn(Return):
    matches = (('tag', 'salt/run/*/ret'),)

    def __init__(self, *args, **kwargs):
        super(RunReturn,self).__init__(*args,**kwargs)
        self.success = self.dat.get('success', NA)
        self.returnd = self.dat.get('return', 0)

class JCReturn(Return):
    matches = (('tag', 'uevent/job_cache/*/ret/*'),)

class EventSend(Event):
    matches = (
        ('cmd', '_minion_event'),
    )

    def __init__(self, *args, **kwargs):
        super(EventSend,self).__init__(*args,**kwargs)

        dat = self.dat
        while dat.get('cmd') == '_minion_event' and 'data' in dat:
            dat = dat['data']

        self.sent = {}
        self.sent = copy.deepcopy(dat)
        to_remove = set()
        for k in self.sent:
            if k.startswith('__'):
                to_remove.add(k)
        for k in to_remove:
            del self.sent[k]

    @property
    def what(self):
        return ( self.tag, json.dumps(self.sent) )


# These two aren't very DRY ... I wanted to do this fjid/what stuff as a mixin,
# but apparently that won't work with properties or ... it failed in some other way
class FindJobPub(Publish):
    matches = Publish.matches + ( ('fun', 'saltutil.find_job'), )

    @property
    def fjid(self):
        a = self.args
        if a:
            return a[0]

    @property
    def what(self):
        return 'fjid={0}'.format(self.fjid or '?')


class FindJobRet(Return):
    matches = Return.matches  + ( ('fun', 'saltutil.find_job'), )

    @property
    def fjid(self):
        a = self.args
        if a:
            return a[0]

    @property
    def what(self):
        return 'fjid={0}'.format(self.fjid or '?')
