
import warnings

import pytest
from saltdump.util import read_event_file

warnings.filterwarnings("ignore", category=DeprecationWarning)

@pytest.fixture
def pinglog_json():
    return list(read_event_file('t/_ping.log'))
