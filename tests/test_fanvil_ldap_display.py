# SPDX-License-Identifier: MIT
"""The X3U Pro projection uses its supported LDAP display attributes."""

import re
import xml.etree.ElementTree as ET

import pytest
from test_catalog import load_bundle, only_output

from phone_profiles.build import UPSTREAM, fixture_context
from phone_profiles.render import normalized_context


def test_retained_x3upro_source_uses_cn_for_ldap_display():
    source = (UPSTREAM / "fanvil/x3u-pro/{$mac}.cfg").read_text(encoding="utf-8-sig")
    assert re.findall(r"<Displayname>(.*?)</Displayname>", source) == ["cn"] * 5


@pytest.mark.parametrize(
    "requested,expected,label",
    [
        (None, "cn", "P4"),
        ("displayName", "cn", "P4"),
        ("cn", "cn", "P4"),
        ("sn", "sn", "Patio"),
    ],
)
def test_x3upro_normalized_ldap_name_default_is_usable_by_native_parser(requested, expected, label):
    profile, templates = load_bundle("fanvil/x3u-pro")
    context = fixture_context()
    context["directory"] = {
        "ldap": {
            "host": "192.0.2.10",
            "port": 1389,
            "name_attributes": "cn sn" if requested == "sn" else "cn",
            "number_attributes": "telephonenumber mobile",
        }
    }
    if requested is not None:
        context["directory"]["ldap"]["display_attribute"] = requested
    context = normalized_context(context)
    assert context["directory"]["ldap"]["display_attribute"] == (requested or "displayName")
    root = ET.fromstring(only_output(profile, templates, context))
    attribute = root.find("./phone/ldap/Displayname").text
    assert attribute == expected
    assert (
        root.find("./phone/ldap/NameAttr").text == context["directory"]["ldap"]["name_attributes"]
    )
    assert root.find("./phone/ldap/port").text == "1389"
    directory_entry = {"cn": "P4", "sn": "Patio", "telephonenumber": "430"}
    assert directory_entry[attribute] == label
    assert directory_entry["telephonenumber"] == "430"
