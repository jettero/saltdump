
from saltdump.util import classify_event
from saltdump.event import Event

def test_classify(pinglog_json):
    for evj in pinglog_json:
        ev = classify_event( evj )
        assert isinstance( ev, Event )
