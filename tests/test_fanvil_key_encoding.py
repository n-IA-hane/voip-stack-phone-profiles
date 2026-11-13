# SPDX-License-Identifier: MIT
"""Semantic key goldens use pinned Fusion vendor data, not native web UI enums."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_catalog import load_bundle, only_output

from phone_profiles.build import fixture_context

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/fusionpbx_fanvil_functions.json").read_text()
)


def test_pinned_vendor_definitions_distinguish_new_call_transfer_and_speed_dial():
    assert FIXTURE["upstream_commit"] == "07f0d76acd044e8a07d2f87aeb50bf59f856393b"
    assert FIXTURE["source_path"] == "app/devices/app_config.php"
    functions = FIXTURE["functions"]
    assert (functions["blf_new"]["description"], functions["blf_new"]["value"]) == (
        "BLF - New Call",
        "bc",
    )
    assert functions["blf_axfer"]["value"] == "ba"
    assert functions["blf_conference"]["value"] == "bf"
    assert functions["speed_dial"]["value"] == "f"
    # Numeric90 is a native web form enum, absent from vendor config values.
    assert "90" not in {entry["value"] for entry in functions.values()}


@pytest.mark.parametrize(
    "identity,group", [("fanvil/x3u-pro", "dssSide"), ("fanvil/x4u", "internal")]
)
@pytest.mark.parametrize(
    "function,semantic",
    [
        ("blf", "blf_new"),
        ("queue_login", "blf_new"),
        ("queue_pause", "blf_new"),
        ("park", "blf_new"),
        ("speed_dial", "speed_dial"),
    ],
)
def test_semantic_memory_key_uses_vendor_config_suffix(identity, group, function, semantic):
    profile, templates = load_bundle(identity)
    context = fixture_context()
    context["keys"][0]["function"] = function
    key = ET.fromstring(only_output(profile, templates, context)).find(f"./dsskey/{group}/Fkey")
    assert key.findtext("Type") == "1"
    assert key.findtext("Value") == "430@1/" + FIXTURE["functions"][semantic]["value"]
    assert key.findtext("Value") != "430@1/90"
    assert key.findtext("Title") == "P4"


@pytest.mark.parametrize(
    "identity,group", [("fanvil/x3u-pro", "dssSide"), ("fanvil/x4u", "internal")]
)
def test_line_key_keeps_its_type_and_sip_identity_without_memory_suffix(identity, group):
    profile, templates = load_bundle(identity)
    context = fixture_context()
    context["keys"][0].update(function="line", dial_target="", event_package="")
    key = ET.fromstring(only_output(profile, templates, context)).find(f"./dsskey/{group}/Fkey")
    assert key.findtext("Type") == "2" and key.findtext("Value") == "SIP1"
