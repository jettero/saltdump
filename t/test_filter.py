
from saltdump.filter import build_filter

def test_filters():
    f1 = build_filter('thing1')
    assert f1('thing1')
    assert not f1('thing2')

    f2 = build_filter('thing1 or thing2')
    assert f2('thing1')
    assert f2('thing2')

    f2 = build_filter('thing* or thang*')
    assert f2('thing1')
    assert f2('thing2')
    assert f2('thang1')
    assert f2('thang2')
    assert not f2('thung1')
    assert not f2('thung2')
