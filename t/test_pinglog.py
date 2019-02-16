
import logging

from saltdump.util import classify_event
from saltdump.event import Event

log = logging.getLogger(__name__)

def test_classify(pinglog_json):
    for evj in pinglog_json:
        ev   = classify_event(evj)
        stru = ev.structured
        sdat = stru['data']

        log.debug('pinglog dat: %s', evj)
        log.debug('  classifed: %s', ev)
        log.debug(' structured: %s', stru)

        assert isinstance( ev, Event )
        assert stru.get('path') == ev.tag
        assert sdat.get('jid')  == ev.jid
