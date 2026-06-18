"""Regression tests for the updater version parser.

The catastrophic bug (v0.5.3 -> v0.5.4): an old release tagged `v354.221` (an
FH6 BUILD number, not an app version) parsed as version (354, 221), which
outranked (0, 5, 3) — so "pick the highest version" auto-downgraded everyone to
the original build. The parser must only accept 3-component X.Y.Z app versions
and ignore 2-component build numbers entirely.
"""

from fd6.gui.updater import _parse_version, _is_newer


def test_build_numbers_are_not_versions():
    # FH6 build numbers (2-component) must NEVER parse as a version.
    assert _parse_version("v354.221") == ()
    assert _parse_version("364.933") == ()
    assert _parse_version("Build 354.221") == ()


def test_real_app_versions_parse():
    assert _parse_version("Multi-Support-v3456-0.5.3") == (0, 5, 3)
    assert _parse_version("Multi-Support-v3456-0.5.2") == (0, 5, 2)
    assert _parse_version("v0.5.10") == (0, 5, 10)
    assert _parse_version("Forza Designer 6+ 0.5.4 auto-updater") == (0, 5, 4)


def test_build_number_never_outranks_app_version():
    # The exact downgrade scenario: a build-number release must not be "newer".
    assert _is_newer("v354.221", "0.5.3") is False
    assert _is_newer("Multi-Support-v3456-0.5.4", "0.5.3") is True
    assert _is_newer("Multi-Support-v3456-0.5.3", "0.5.4") is False


def test_no_version_means_not_newer():
    assert _parse_version("Multi-Support-v3456") == ()
    assert _is_newer("Multi-Support-v3456", "0.5.4") is False
