# coding: utf-8

import os
import json
import logging
import time

import salt.minion
import salt.utils
from salt.version import __version__ as saltversion
from .config import SaltConfigMixin

log = logging.getLogger(__name__)

class SocketReadPermissionError(OSError):
    pass

class JobCachePermissionError(OSError):
    pass

class MasterMinionJidNexter(object):
    def get_jids(self): return []
    def get_jid(self):  pass
    def get_load(self): pass

    def __init__(self, opts):
        # this is meant to somewhat replicate what happens in
        # salt/runners/jobs.py in print_job()

        mminion = salt.minion.MasterMinion(opts)
        for fn in ('get_jids', 'get_jid', 'get_load',):
            for i in ('ext_job_cache', 'master_job_cache',):
                fn_full = '{0}.{1}'.format( opts.get(i), fn )
                if fn_full in mminion.returners:
                    log.debug("using MasterMinion.returners[{0}] for MasterMinionJidNexter.{1}".format(fn_full,fn))
                    setattr(self, fn, mminion.returners[fn_full])
                    break
        self.g = self.gen()

    def gen(self):
        try:
            jids = sorted(self.get_jids())
        except OSError as e:
            raise JobCachePermissionError(e)

        for jid in sorted(self.get_jids()):
            # This is a continuation of the things that happen in
            # salt/runners/jobs.py in print_job()

            # It is trickey, the master doesn't really store the event in the
            # job cache. It has to be reconstructed from various sources and
            # some extra trash has to be removed to make it sorta look right
            # again.

            # This is different form what happens in
            # salt/runners/jobs.py via _format_jid_instance(jid,job).
            # Similar though.

            load = self.get_load(jid)
            mini = load.pop('Minions', ['local'])

            try:
                jdat = self.get_jid(jid)
            except Exception as e:
                jdat = {'_jcache_exception': "exception trying to invoke get_jid({0}): {1}".format(jid,e)}

            for id in mini:
                mjdat = jdat.get(id)
                if mjdat is None:
                    log.info("minion id={0} did not return in jid={1} (but was expected to do so)".format(id,jid))
                    continue

                fake_return = {
                    "jid": jid,
                    "id": id,
                    "fun": load.get('fun'),
                    "fun_args": load.get('arg'),
                    "cmd": "_return", 
                    "_stamp": salt.utils.jid.jid_to_time(jid), # spurious!! this isn't really the return time

                    # I can't think of any way to fake these in a general way
                    # and the jobcache doesn't store them
                    "retcode": None,
                    "success": None,
                }

                fake_return.update(mjdat)

                tag = "salt/job/{0}/ret/{1}".format(jid,id)
                _jdat = {'get_load':load, 'get_jid_{0}'.format(id): mjdat}

                yield {'from_job_cache': time.time(), 'tag': tag, '_raw':_jdat, 'data': fake_return}

    def next(self):
        if self.g:
            try:
                return self.g.next()
            except StopIteration:
                self.g = False

class MasterMinion(SaltConfigMixin):
    ppid = kpid = None

    def __init__(self, args=None, preproc=None, replay_file=None, replay_only=False, replay_job_cache=None):
        if replay_only:
            replay_job_cache = True

        self.preproc          = preproc
        self.replay_file      = replay_file
        self.replay_only      = replay_only
        self.replay_job_cache = replay_job_cache

        # overwrite all self vars from args (where they match)
        if args:
            for k,v in vars(args).iteritems():
                if hasattr(self,k):
                    setattr(self,k,v)

        if not isinstance(self.preproc,list):
            if isinstance(self.preproc,tuple):
                self.preproc = list(self.preproc)
            elif self.preproc is not None:
                self.preproc = [self.preproc]
            else:
                self.preproc = []

        self._init2()

    def _init2(self):
        # look at /usr/lib/python2.7/site-packages/salt/modules/state.py in event()
        self.get_event_args = { 'full': True }
        if saltversion.startswith('2016'):
            self.get_event_args['auto_reconnect'] = True

        if self.replay_file:
            log.debug("opening replay_file=%s", self.replay_file)
            self.replay_fh = open(self.replay_file,'r')
        else:
            self.replay_fh = None

        if self.replay_job_cache:
            self.mmjn = MasterMinionJidNexter(self.mmin_opts)

        if self.replay_only:
            self.sevent = None
        else:
            # NOTE: salt-run state.event pretty=True
            #       is really salt.runners.state.event()
            # which is really salt.modules.state.event()
            # which is really salt.utils.event.get_event()
            self.sevent = salt.utils.event.get_event(
                    'master', # node= master events or minion events
                    self.salt_opts['sock_dir'],
                    self.salt_opts['transport'],
                    opts=self.salt_opts,
                    listen=True)
            socket_fname = os.path.join(self.salt_opts['sock_dir'], 'master_event_pub.ipc')
            if not os.access(socket_fname, os.R_OK):
                raise SocketReadPermissionError('no read permission on {0}'.format(socket_fname))
            # In [1]: os.path.exists('/var/run/salt/master/master_event_pub.ipc')
            # Out[1]: True
            # In [2]: os.access('/var/run/salt/master/master_event_pub.ipc', os.R_OK)
            # Out[2]: False


    def add_preproc(self, *preproc):
        for p in preproc:
            if isinstance(p,list) or isinstance(p,tuple):
                self.add_preproc(*p)
            elif p is not None and p not in self.preproc:
                self.preproc.append(p)

    def next(self):
        ev = None

        if self.replay_fh:
            ev_text = ''
            while True:
                line = self.replay_fh.readline()
                if line:
                    if line.strip(): ev_text += line
                    else: break
                else:
                    self.replay_fh = self.replay_fh.close()
                    break
            if ev_text:
                # this is a pretty weak pre-parse/sanity-check, but it works
                if ev_text.lstrip().startswith('{') and ev_text.rstrip().endswith('}'):
                    ev = json.loads(ev_text)
                    ev['_from_replay'] = self.replay_file

        elif self.replay_job_cache:
            ev = self.mmjn.next()
            if ev is None:
                self.replay_job_cache = self.mmjn = False

        elif self.sevent:
            ev = self.sevent.get_event( **self.get_event_args )

        else:
            log.info("no remaining replay file handles, job caches, or event scanners. FIN")
            return 'FIN'

        for pprc in self.preproc:
            if ev is not None:
                ev = pprc(ev)

        if ev is not None:
            return ev

    def listen_loop(self, callback):
        try:
            while True:
                j = self.next()
                if j is None:
                    continue
                if j == 'FIN':
                    log.debug('internal iterator finished; returning from listen_loop')
                    return
                log.debug("calling callback from listen_loop")
                if not callback(j):
                    break
                if j.get('tag') == 'salt/event/exit':
                    log.debug('tag is %s; returning from listen_loop', j['tag'])
                    return
        except IOError:
            return # probably Broken Pipe from `saltdump | head` (or similar)
        except KeyboardInterrupt:
            pass
