
from saltdump.filter import build_filter

def test_filters():
    f1 = build_filter('thing1')
    assert f1('thing1')
    assert not f1('thing2')

    f2 = build_filter('thing1 or thing2')
    assert f2('thing1')
    assert f2('thing2')

    f3 = build_filter('thing* or thang*')
    assert f3('thing1')
    assert f3('thing2')
    assert f3('thang1')
    assert f3('thang2')
    assert not f3('thung1')
    assert not f3('thung2')

    f4 = build_filter('thing* and *blah*')
    assert not f4('thing')
    assert f4('thing/blah')
    assert f4('thingblah')
    assert not f4('blahthing')
