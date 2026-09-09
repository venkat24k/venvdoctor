from venvdoctor.outdated import _is_outdated, _ver_key


def test_basic_numeric_ordering():
    assert _ver_key("1.2.3") < _ver_key("1.2.4")
    assert _ver_key("1.9.9") < _ver_key("2.0")
    assert _ver_key("1.0") < _ver_key("1.0.1")


def test_prerelease_sorts_before_final():
    assert _ver_key("1.0.0a1") < _ver_key("1.0.0")
    assert _ver_key("1.0.0b1") < _ver_key("1.0.0")
    assert _ver_key("1.0.0rc1") < _ver_key("1.0.0")


def test_prerelease_stage_ordering():
    assert _ver_key("1.0.0a1") < _ver_key("1.0.0b1")
    assert _ver_key("1.0.0b1") < _ver_key("1.0.0rc1")
    assert _ver_key("1.0.0rc1") < _ver_key("1.0.0rc2")


def test_dev_release_sorts_before_prerelease():
    assert _ver_key("1.0.0.dev1") < _ver_key("1.0.0a1")


def test_postrelease_sorts_after_final():
    assert _ver_key("1.0.0") < _ver_key("1.0.0.post1")
    assert _ver_key("1.0.0.post1") < _ver_key("1.0.0.post2")


def test_is_outdated_true_for_newer_latest():
    assert _is_outdated("1.0.0", "1.0.1") is True
    assert _is_outdated("1.0.0rc1", "1.0.0") is True


def test_is_outdated_false_for_same_or_older():
    assert _is_outdated("1.0.1", "1.0.1") is False
    assert _is_outdated("1.0.1", "1.0.0") is False


def test_unparseable_version_falls_back_to_string_inequality():
    # Garbage input shouldn't raise; it should degrade gracefully.
    assert _is_outdated("not-a-version", "not-a-version") is False
