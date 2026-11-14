# SPDX-License-Identifier: MIT
"""A directory transport is supported only by the declared projection."""

import pytest
from test_catalog import catalog, load_bundle

from phone_profiles.build import fixture_context
from phone_profiles.render import render


def test_catalog_ldap_profiles_declare_their_plain_transport():
    for metadata in catalog()["profiles"]:
        if "ldap" in metadata["capabilities"].get("functions", []):
            assert metadata["capabilities"]["ldap_modes"] == ["plain"]


def test_native_http_apply_stays_opt_in_and_pending_physical_qualification():
    profile, _ = load_bundle("fanvil/x3u-pro")
    method = profile["capabilities"]["apply"]
    assert method["method"] == "fanvil_native_http" and method["qualified"] is False
    assert method["model"] == "X3U Pro" and method["firmwares"] == ["2.12.20"]


@pytest.mark.parametrize("mode", ["ldaps", "starttls"])
def test_fanvil_never_sends_plain_bind_to_an_unmapped_tls_service(mode):
    profile, templates = load_bundle("fanvil/x3u-pro")
    context = fixture_context()
    context.setdefault("directory", {}).setdefault("ldap", {}).update(host="192.0.2.10", mode=mode)
    with pytest.raises(ValueError, match="phone_ldap_mode_unsupported"):
        render(profile, templates, context)
