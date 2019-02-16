# coding: utf-8

from __future__ import print_function

import os
import sys
import click
import logging
import warnings

from .filter import build_filter
from .version import version as saltdump_version
from .master_minion import MasterMinion, SocketReadPermissionError, JobCachePermissionError
from .event import classify_event, JidCollector
from .misc import Attr

log = logging.getLogger(__name__)

oargs = list(sys.argv)

class CmdRunner(Attr):
    flush_me = False
    printed = 0
    jc = None

    def __init__(self, **opt):
        super(CmdRunner, self).__init__(**opt)
        self.filter = build_filter(*self.filter)
        self.mm = MasterMinion(replay_only=self.replay_only,
            replay_job_cache=self.replay_job_cache)

        if opt['show_job_info']:
            self.jc = JidCollector()
            self.jc.on_change(self.print_job_info)

    def _print_event(self, cev):
        if self.output_format == 'json':
            out = cev.json()
        elif self.output_format == 'jsonl':
            out = cev.json(indent=0)
        elif self.output_format == 'salt':
            out = cev.outputter(default_outputter=self.salt_outputter)
        elif self.output_format == 'stru':
            out = cev.jsonstru
        elif self.output_format == 'txt':
            out = cev.short
        else:
            out = u"fmt={0}? {1}".format(self.output_format, cev.jsonl)
        sys.stdout.write( unicode(out) + '\n' )
        self.flush_me = True

    def print_job_info(self, jitem, actions):
        log.debug("print_job_info(%s, %s)", jitem, actions)
        self._print_event(jitem)

    def print_event(self, ev):
        cev = classify_event(ev)
        if self.filter(cev.tag):
            self._print_event(cev)
            self.printed += 1 # do not increment in _print_event, that also prints non-events sometimes
        if self.jc:
            self.jc.examine_event(cev)
        if self.flush_me:
            if not self.no_line_buffer:
                sys.stdout.flush()
                self.flush_me = False
        if self.count is not None and self.printed >= self.count:
            return False # meaning we're done
        return True # meaning continue reading events

    def listen_loop(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.mm.listen_loop(self.print_event)


@click.command()
@click.option('-j', '--show-job-info', is_flag=True, default=False,
    help='show job return counters')
@click.option('-r', '--replay-job-cache', is_flag=True, default=False,
    help='read the salt job cache and replay them as if they were just intercepted')
@click.option('-R', '--replay-only', is_flag=True, default=False,
    help='once the salt job cache is replayed, exit without listening to the salt sockets')
@click.option('-B', '--no-line-buffer', is_flag=True, default=False,
    help='by default saltdump flushes output after emitting an event')
@click.option('-S', '--no-sudo-root', is_flag=True, default=False,
    help='by default, if saltdump cannot read the salt sockets or configs, it'
    ' will try to switch to root with sudo')
@click.option('-V', '--version', is_flag=True, default=False, help='print version and exit')
@click.option('-l', '--level', type=str, default='error', help='logging level, default: error')
@click.option('-c', '--count', type=int, help='after emitting this many events, exit normally')
@click.option('-o', '--output-format',
    type=click.Choice(['json', 'txt', 'jsonl', 'salt', 'stru']),
    default='txt',
    help='''txt: format events as line of text intended for humans (default)

    json: output events as pretty json

    jsonl: output events as one-line json

    salt: try to output events using the Salt outputters

    stru: output one-line json intended for structured logging (e.g., Splunk,
        LogStash, etc).  Some fields are added or removed for consistency and
        public 0mq keys found in auth events are replaced with a much shorter
        smattering of characters from the key.
    ''')
@click.option('-O', '--salt-outputter', type=str, default='nested')
@click.argument('filter', nargs=-1)
def saltdump(version, level, no_sudo_root, **opt):
    ''' FILTER (if given) is a glob or logical string of globs.

        \b
        examples:
          saltdump salt/job/*
          saltdump salt/* and not salt/auth

        --show-job-info (-j) tells saltdump to reveal its internal job tracking
        counters.  The job info is formatted as if it were Salt event data, but
        is not actually generated by Salt.
    '''
    if version:
        print(saltdump_version)
        sys.exit(0)

    if os.environ.get('SALTDUMP_NO_SUDO_ROOT'):
        opt['no_sudo_root'] = True

    if opt['output_format'] == 'salt' and not opt['filter']:
        opt['filter'] = ('salt/job/*/ret*',)

    level = logging.getLevelName(level.upper())
    if not isinstance(level, int):
        level = logging.DEBUG
    logging.root.handlers = []
    logging.basicConfig(level=level)
    log.debug('logging (re)configured')

    try:
        runner = CmdRunner(**opt)
        runner.listen_loop()

    except (JobCachePermissionError, SocketReadPermissionError) as e:
        if not no_sudo_root:
            uid = os.getuid()
            if uid > 0:
                log.error('%s; uid=%d > 0, switching to root', e, uid)
                os.execvp('sudo', ['sudo'] + oargs)
        sys.stderr.write("FATAL: {0}\n".format(e))
        sys.exit(1)
