from version import VERSION, is_newer, parse_version


def test_version_comparison():
    assert parse_version('v1.10.0') == (1, 10, 0)
    assert parse_version('2.1') == (2, 1, 0)
    assert is_newer('1.10.0', '1.9.3')
    assert not is_newer('v1.1.0', '1.1.0')
    assert not is_newer('1.0.9', '1.1.0')
    assert len(parse_version(VERSION)) == 3
