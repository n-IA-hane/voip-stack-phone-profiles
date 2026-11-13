# SPDX-License-Identifier: MIT
"""Independent vendor goldens for owned slot retirement and explicit identities."""

import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from test_catalog import catalog, load_bundle, only_output

from phone_profiles.build import fixture_context
from phone_profiles.render import normalized_context, render

DOCUMENTED = {
    "fanvil/x3u-pro",
    "snom/720",
    "snom/7xx",
    "yealink/t42u",
    "yealink/t43u",
    "yealink/t46g",
    "yealink/t46s",
    "yealink/t46u",
}


def context():
    return fixture_context()


def cfg(body):
    return dict(
        tuple(part.strip() for part in line.split("=", 1))
        for line in body.splitlines()
        if line.strip() and not line.startswith("#")
    )


def test_legacy_context_gets_empty_retirement_without_mutating_input():
    original = context()
    normalized = normalized_context(original)
    assert normalized["retired"] == {"keys": [], "lines": []}
    assert "retired" not in original


@pytest.mark.parametrize("identity", ["snom/7xx", "snom/8xx"])
@pytest.mark.parametrize("line", [1, 2])
def test_snom_fkey_is_in_its_sibling_group_and_uses_explicit_identity(identity, line):
    profile, templates = load_bundle(identity)
    # Serializer contract fixture advertises two identities; published profile
    # limits remain unchanged. Official Snom examples bind context1 and2.
    profile = deepcopy(profile)
    profile["capabilities"]["max_lines"] = 2
    c = context()
    c["lines"].append({**c["lines"][0], "slot": 2, "username": "fixture2"})
    c["keys"][0]["line"] = line
    root = ET.fromstring(only_output(profile, templates, c))
    assert root.find("./phone-settings/fkey") is None
    (key,) = root.findall("./functionKeys/fkey")
    assert key.attrib["idx"] == "0" and key.attrib["context"] == str(line)
    assert key.text.strip() == "blf 430"
    assert len(root.findall("./phone-settings/user_active")) == 2


def test_capabilities_are_explicit_and_only_verified_profiles_allow_removal():
    for entry in catalog()["profiles"]:
        caps = entry["capabilities"]
        assert type(caps["clear_keys"]) is bool and type(caps["disable_lines"]) is bool
        supported = entry["id"] in DOCUMENTED and entry["status"] == "software_validated"
        assert caps["clear_keys"] is supported
        assert caps["disable_lines"] is supported
        if supported:
            assert caps["retirement_evidence"]
            assert entry["qualification"]["physical"] is False


@pytest.mark.parametrize("identity", ["fanvil/x3u-pro", "snom/7xx", "yealink/t46s"])
def test_owned_key_present_removed_and_readded_has_explicit_vendor_commands(identity):
    profile, templates = load_bundle(identity)
    c = context()
    initial = only_output(profile, templates, c)
    c["keys"] = []
    c["retired"] = {"keys": ["1"], "lines": []}
    removed = only_output(profile, templates, c)
    assert removed == only_output(profile, templates, c)
    if profile["vendor"] == "yealink":
        values = cfg(removed)
        assert values["linekey.1.type"] == "0"
        assert values["linekey.1.type"] not in {"%NULL%", "!NULL!"}
        assert {values[f"linekey.1.{name}"] for name in ("value", "label", "extension")} == {
            "%NULL%"
        }
        assert not any(key.startswith("linekey.2.") for key in values)
    elif profile["vendor"] == "snom":
        (key,) = ET.fromstring(removed).findall("./functionKeys/fkey")
        assert key.attrib["idx"] == "0" and key.text.strip() == "none"
        assert key.attrib["label"] == ""
    else:
        (key,) = ET.fromstring(removed).findall("./dsskey/dssSide/Fkey")
        assert key.attrib["index"] == "1" and key.findtext("Type") == "0"
        assert key.find("Value").text is None and key.find("Title").text is None
    c["keys"] = context()["keys"]
    c["retired"]["keys"] = []
    assert only_output(profile, templates, c) == initial


@pytest.mark.parametrize("identity", ["fanvil/x3u-pro", "snom/7xx", "yealink/t46s"])
def test_owned_line_disable_does_not_require_or_emit_removed_credentials(identity):
    profile, templates = load_bundle(identity)
    c = context()
    initial = only_output(profile, templates, c)
    c.update(lines=[], keys=[], retired={"keys": ["1"], "lines": ["1"]})
    removed = only_output(profile, templates, c)
    assert "fixture-not-a-device-secret" not in removed and "fixture480" not in removed
    if profile["vendor"] == "yealink":
        values = cfg(removed)
        assert values["account.1.enable"] == "0"
        assert {values[f"account.1.{name}"] for name in ("user_name", "auth_name", "password")} == {
            "%NULL%"
        }
        assert not any(key.startswith("account.2.") for key in values)
    elif profile["vendor"] == "snom":
        (line,) = ET.fromstring(removed).findall("./phone-settings/user_active")
        assert line.attrib["idx"] == "1" and line.text == "off"
    else:
        (line,) = ET.fromstring(removed).findall("./sip/line")
        assert line.attrib["index"] == "1" and line.findtext("EnableReg") == "0"
    assert only_output(profile, templates, context()) == initial


def test_known_unowned_fanvil_slot_is_never_reset():
    profile, templates = load_bundle("fanvil/x3u-pro")
    c = context()
    c["retired"] = {"keys": ["2"], "lines": ["2"]}
    root = ET.fromstring(only_output(profile, templates, c))
    assert [key.attrib["index"] for key in root.findall("./dsskey/dssSide/Fkey")] == ["1", "2"]
    assert [line.attrib["index"] for line in root.findall("./sip/line")] == ["1", "2"]
    assert root.find("./dsskey/dssSide/Fkey[@index='3']") is None
    assert root.find("./sip/line[@index='3']") is None


@pytest.mark.parametrize(
    "retired",
    [
        None,
        False,
        [],
        {"other": []},
        {"keys": "1"},
        {"keys": [1]},
        {"keys": [True]},
        {"keys": ["01"]},
        {"keys": ["0"]},
        {"keys": ["9"]},
        {"keys": ["1", "1"]},
        {"lines": ["0"]},
        {"lines": ["7"]},
        {"lines": [False]},
    ],
)
def test_invalid_or_foreign_retired_slots_are_rejected(retired):
    profile, templates = load_bundle("fanvil/x3u-pro")
    c = context()
    c.update(keys=[], lines=[], retired=retired)
    with pytest.raises(ValueError):
        only_output(profile, templates, c)


@pytest.mark.parametrize("kind", ["keys", "lines"])
def test_slot_cannot_be_configured_and_retired_in_the_same_revision(kind):
    profile, templates = load_bundle("fanvil/x3u-pro")
    c = context()
    c["retired"] = {kind: ["1"]}
    with pytest.raises(ValueError):
        only_output(profile, templates, c)


@pytest.mark.parametrize("kind", ["keys", "lines"])
@pytest.mark.parametrize("old_profile", [False, True])
def test_unsupported_and_old_profiles_fail_closed_only_for_nonempty_removal(kind, old_profile):
    profile, templates = load_bundle("grandstream/grp2614")
    if old_profile:
        profile["capabilities"].pop("clear_keys")
        profile["capabilities"].pop("disable_lines")
    c = context()
    assert render(profile, templates, c)
    c["retired"] = {"keys": [], "lines": []}
    assert render(profile, templates, c)
    c["retired"][kind] = ["1"]
    with pytest.raises(ValueError):
        render(profile, templates, c)
