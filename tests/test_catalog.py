# SPDX-License-Identifier: MIT
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined

from phone_profiles.build import ROOT, UPSTREAM, canonical, fixture_context
from phone_profiles.render import render, validate_context
from phone_profiles.smarty import compile_template

SAMPLES = [
    "fanvil/x3u-pro",
    "fanvil/x4u",
    "yealink/t46s",
    "yealink/t46u",
    "snom/7xx",
    "grandstream/grp2614",
    "grandstream/gxp2170",
]


def catalog():
    return json.loads((ROOT / "manifest.json").read_text())


def load_bundle(profile_id):
    entry = next(p for p in catalog()["profiles"] if p["id"] == profile_id)
    with zipfile.ZipFile(ROOT / entry["bundle"]["path"]) as z:
        profile = json.loads(z.read("profile.json"))
        templates = {p: z.read(p).decode() for p in z.namelist() if p.startswith("templates/")}
    return profile, templates


def only_output(profile, templates, context):
    return next(iter(render(profile, templates, context).values())).decode()


def source_of(profile_id):
    parent = UPSTREAM / profile_id
    # A model can contain both MAC.boot and MAC.cfg. Golden sources are explicit,
    # independent of directory iteration order and of the builder's selection.
    name = "{$mac}.cfg" if profile_id.startswith(("fanvil/", "yealink/")) else "{$mac}.xml"
    return (parent / name).read_text(encoding="utf-8-sig")


def original_fragment(fragment, context):
    env = Environment(
        undefined=StrictUndefined, autoescape=False, extensions=["jinja2.ext.loopcontrols"]
    )
    return env.from_string(compile_template(fragment)).render(context).strip()


@pytest.mark.parametrize("profile_id", SAMPLES)
def test_seven_samples_differential_account_and_key_against_original_fragments(profile_id):
    """Compare the sparse result with actual pinned upstream field expressions.

    This is a differential against the supported source subset, not a claim of
    execution in the original PHP Smarty engine or physical firmware.
    """
    profile, templates = load_bundle(profile_id)
    context = fixture_context()
    context["lines"][0].update(auth_username="fixture-auth", display_name="Name & <UTF8 é>")
    if profile["vendor"] == "snom":
        context["lines"][0]["auth_username"] = "fixture480"
    rendered = only_output(profile, templates, context)
    source = source_of(profile_id)
    vendor = profile["vendor"]
    legacy_line = {
        "user_id": "fixture480",
        "auth_id": context["lines"][0]["auth_username"],
        "password": context["lines"][0]["password"],
        "display_name": "Name & <UTF8 é>",
        "server_address": "192.0.2.10",
        "sip_port": 5060,
        "register_expires": 3600,
        "sip_transport": "udp",
        "line_number": 1,
    }
    legacy = {"account": {1: legacy_line}, "user": {1: legacy_line}, "row": legacy_line}
    if vendor == "fanvil":
        parsed = ET.fromstring(rendered)
        for name, field in [
            ("PhoneNumber", "user_id"),
            ("RegisterUser", "auth_id"),
            ("RegisterPswd", "password"),
            ("RegisterAddr", "server_address"),
        ]:
            fragment = re.search(rf"<{name}>(.*?)</{name}>", source, re.DOTALL)[1]
            assert parsed.find(f"./sip/line/{name}").text == original_fragment(fragment, legacy)
            assert parsed.find(f"./sip/line/{name}").text == str(legacy_line[field])
        fragment = re.search(
            r'<Fkey index="\{\$row.device_key_id\}">(.*?)</Fkey>', source, re.DOTALL
        )[0]
        row = {
            "device_key_id": 1,
            "device_key_line": 1,
            "device_key_type": 90,
            "device_key_value": "430",
            "device_key_label": "P4",
            "device_key_icon": "",
        }
        oracle = ET.fromstring(original_fragment(fragment, {"row": row}))
        emitted = parsed.find("./dsskey/internal/Fkey")
        assert [emitted.find(n).text for n in ("Type", "Value", "Title")] == [
            oracle.find(n).text for n in ("Type", "Value", "Title")
        ]
        assert emitted.find("Value").text == "430@1/90"
    elif vendor == "yealink":
        config = dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)
        config = {k.strip(): v.strip() for k, v in config.items()}
        # Sources use either a foreach row or a numbered account map.
        for suffix, field in [
            ("user_name", "user_id"),
            ("auth_name", "auth_id"),
            ("password", "password"),
        ]:
            if suffix == "user_name":
                fragment = re.search(
                    r"\{if isset\(\$(?:row|account\.1)\.server\.1\.address\)\}.*?\{/if\}",
                    source,
                    re.DOTALL,
                )[0]
                oracle = original_fragment(fragment, legacy).split("=", 1)[1].strip()
            else:
                fragment = next(
                    line.split("=", 1)[1].strip()
                    for line in source.splitlines()
                    if re.match(rf"account\..+\.{suffix}\s*=", line)
                )
                oracle = original_fragment(fragment, legacy)
            assert config[f"account.1.{suffix}"] == oracle
            assert config[f"account.1.{suffix}"] == str(legacy_line[field])
        assert config["linekey.1.value"] == "430"
        assert config["linekey.1.type"] == "16"
    elif vendor == "snom":
        parsed = ET.fromstring(rendered)
        for tag, field in [("user_name", "user_id"), ("user_pass", "password")]:
            fragment = re.search(rf'<{tag} idx="1"[^>]*>(.*?)</{tag}>', source, re.DOTALL)[1]
            assert parsed.find(f"./phone-settings/{tag}").text == original_fragment(
                fragment, legacy
            )
            assert parsed.find(f"./phone-settings/{tag}").text == str(legacy_line[field])
        fkey = parsed.find("./functionKeys/fkey")
        assert fkey.attrib["idx"] == "0"
        assert fkey.attrib["context"] == "1"
        assert fkey.text.strip() == "blf 430"
    else:
        parsed = ET.fromstring(rendered)
        items = {x.attrib["name"]: x.text for x in parsed.findall("./config/item")}
        for suffix, field in [
            ("sip.userid", "user_id"),
            ("sip.subscriber.userid", "auth_id"),
            ("sip.subscriber.password", "password"),
        ]:
            fragment = re.search(
                rf'<item name="account\.\{{\$row.line_number\}}\.{re.escape(suffix)}">(.*?)</item>',
                source,
                re.DOTALL,
            )[1]
            assert items[f"account.1.{suffix}"] == original_fragment(fragment, legacy)
            assert items[f"account.1.{suffix}"] == str(legacy_line[field])
        assert items["pks.vpk.1.keyMode"] == "1"
        assert items["pks.vpk.1.value"] == "430"


def assert_sparse(profile, output):
    vendor = profile["vendor"]
    if vendor == "yealink":
        keys = [line.split("=", 1)[0].strip() for line in output.splitlines() if "=" in line]
        for key in keys:
            assert re.fullmatch(
                r"account\.\d+\.(enable|label|display_name|auth_name|user_name|password|sip_server\.1\.(address|port|transport_type|expires)|outbound_proxy\.1\.address)|linekey\.\d+\.(type|line|value|label|extension)",
                key,
            ), key
        return
    root = ET.fromstring(output)
    if vendor == "fanvil":
        assert {n.tag for n in root} <= {"Version", "sip", "dsskey", "timePlan", "phone", "ap"}
        for line in root.findall("./sip/line"):
            assert {n.tag for n in line} <= {
                "PhoneNumber",
                "DisplayName",
                "RegisterAddr",
                "RegisterPort",
                "RegisterUser",
                "RegisterPswd",
                "RegisterTTL",
                "EnableReg",
                "Transport",
                "ProxyAddr",
            }
        assert root.find("./net") is None
        for parent in ("timePlan", "phone"):
            node = root.find(parent)
            if node is not None:
                assert {n.tag for n in node} <= {"display", "ldap"}
        ap = root.find("ap")
        if ap is not None:
            assert {n.tag for n in ap} == {"FlashServerIP"}
    elif vendor == "snom":
        assert {n.tag for n in root.find("phone-settings")} <= {
            "user_active",
            "user_realname",
            "user_name",
            "user_pass",
            "user_host",
            "user_expiry",
        }
        assert {n.tag for n in root} <= {"phone-settings", "functionKeys"}
        assert all(n.tag == "fkey" for n in root.findall("./functionKeys/*"))
    else:
        for node in root.find("config"):
            if node.tag == "item":
                assert re.fullmatch(
                    r"account\.\d+\.(enable|name|sip\.(server\.1\.address|userid|subscriber\.(userid|password|name)|transport))|pks\.vpk\.\d+\.(keyMode|account|description|value)",
                    node.attrib["name"],
                )
            else:
                assert node.tag in {"P271", "P270", "P47", "P35", "P36", "P34", "P3", "P183"}


def test_every_servable_profile_bundle_hash_license_sources_and_sparse_effective_output():
    manifest = catalog()
    unsigned = {k: v for k, v in manifest.items() if k != "catalog_revision"}
    assert manifest["catalog_revision"] == sha256(canonical(unsigned)).hexdigest()
    assert len(manifest["profiles"]) == 202
    assert len({p["id"] for p in manifest["profiles"]}) == 202
    served = 0
    for entry in manifest["profiles"]:
        if entry["status"] == "imported":
            assert entry.get("reason") and "bundle" not in entry
            continue
        served += 1
        blob = (ROOT / entry["bundle"]["path"]).read_bytes()
        assert len(blob) == entry["bundle"]["size"]
        assert sha256(blob).hexdigest() == entry["bundle"]["sha256"]
        with zipfile.ZipFile(BytesIO(blob)) as z:
            assert all(not p.startswith("/") and ".." not in Path(p).parts for p in z.namelist())
            profile = json.loads(z.read("profile.json"))
            assert profile["id"] == entry["id"]
            assert z.read("LICENSES/MPL-1.1.txt").startswith(
                b"                          MOZILLA PUBLIC LICENSE"
            )
            assert b"Mark J Crane" in z.read("NOTICE")
            provenance = json.loads(z.read("provenance.json"))
            assert provenance["upstream_commit"] == manifest["upstream"]["commit"]
            assert provenance["modifications"][0]["date"] == "2026-11-11"
            for record in provenance["files"]:
                rel = record["path"].split("/" + entry["id"] + "/", 1)[1]
                assert sha256(z.read("source/original/" + rel)).hexdigest() == record["sha256"]
            templates = {p: z.read(p).decode() for p in z.namelist() if p.startswith("templates/")}
            context = fixture_context()
            if not profile["capabilities"]["key_slots"]:
                context["keys"] = []
            output = only_output(profile, templates, context)
            assert "fixture480" in output and "fixture-not-a-device-secret" in output
            if context["keys"]:
                assert "430" in output and "P4" in output
            assert "{$" not in output and "{%" not in output and "{{" not in output
            assert_sparse(profile, output)
    assert served >= 90  # A broad software catalog, not seven hardware-limited models.


def test_excluded_assets_and_static_key_never_enter_repository_inventory_or_bundles():
    provenance = json.loads((ROOT / "provenance/fusionpbx.json").read_text())
    assert len(provenance["files"]) == 612
    assert len(provenance["excluded"]) == 2
    for row in provenance["files"]:
        rel = row["path"].split("resources/templates/provision/", 1)[1]
        data = (UPSTREAM / rel).read_bytes()
        assert sha256(data).hexdigest() == row["sha256"]
        assert b"PRIVATE KEY-----" not in data and b"\0" not in data
        data.decode("utf-8-sig")
    assert not list(UPSTREAM.rglob("*.ott"))
    assert not (UPSTREAM / "grandstream/gds3710").exists()


def test_fanvil_six_lines_three_keys_utf8_ldap_and_no_unselected_settings():
    profile, templates = load_bundle("fanvil/x3u-pro")
    c = fixture_context()
    c["physical"].update(name="È & <Casa>", language="it")
    c["lines"] = [dict(c["lines"][0], slot=i) for i in range(1, 7)]
    c["keys"] = [dict(c["keys"][0], slot=str(i), line=i, label="È Casa") for i in range(1, 4)]
    c["directory"] = {
        "ldap": {
            "host": "192.0.2.10",
            "port": 1389,
            "base_dn": "ou=phonebook,dc=voip",
            "bind_dn": "uid=fixture480,ou=accounts,dc=voip",
            "password": "ldap-fixture-only",
            "name_filter": "(|(cn=%)(sn=%))",
            "number_filter": "(|(telephonenumber=%)(mobile=%))",
        }
    }
    c["provisioning"] = {"url": "https://example.invalid/profile?version=1&kind=phone"}
    result = only_output(profile, templates, c)
    root = ET.fromstring(result)
    assert len(root.findall("./sip/line")) == 6
    assert len(root.findall("./dsskey/internal/Fkey")) == 3
    assert root.find("./phone/display/DefaultLanguage").text == "it"
    assert root.find("./phone/ldap/TelAttr").text == "telephonenumber"
    assert root.find("./ap/FlashServerIP").text == c["provisioning"]["url"]
    assert_sparse(profile, result)


def test_missing_credentials_input_injection_and_no_truncation():
    p, templates = load_bundle("fanvil/x3u-pro")
    for mutation in (
        lambda c: c["lines"][0].pop("password"),
        lambda c: c["keys"][0].update(dial_target="€" * 11),
        lambda c: c["keys"][0].update(slot="4"),
        lambda c: c["lines"][0].update(server="x\nnetwork.dns=evil"),
        lambda c: c["keys"][0].update(subscription_target="different"),
    ):
        c = fixture_context()
        mutation(c)
        with pytest.raises((ValueError, KeyError)):
            render(p, templates, c)
    c = fixture_context()
    c["keys"][0]["dial_target"] = "0" * 31
    assert "0" * 31 in only_output(p, templates, c)


def test_unmanaged_global_fields_do_not_leak_into_output():
    p, templates = load_bundle("fanvil/x3u-pro")
    c = fixture_context()
    c.update(
        dns_server_primary="203.0.113.250",
        admin_password="forbidden-sentinel",
        fanvil_ringtone="forbidden-sentinel",
        fanvil_firmware_path="forbidden-sentinel",
    )
    output = only_output(p, templates, c)
    assert "203.0.113.250" not in output and "forbidden-sentinel" not in output


def test_empty_optional_fields_use_documented_fallbacks():
    p, templates = load_bundle("fanvil/x3u-pro")
    c = fixture_context()
    c["lines"][0].update(auth_username="", display_name="", expires="", outbound_proxy="")
    output = only_output(p, templates, c)
    parsed = ET.fromstring(output)
    assert parsed.find("./sip/line/RegisterUser").text == "fixture480"
    assert parsed.find("./sip/line/DisplayName").text == "Software fixture"
    assert parsed.find("./sip/line/RegisterTTL").text == "3600"
    assert parsed.find("./sip/line/ProxyAddr") is None


def test_unknown_model_and_feature_are_not_silently_rendered():
    p, _ = load_bundle("snom/7xx")
    c = deepcopy(fixture_context())
    c["directory"] = {"ldap": {"host": "192.0.2.10"}}
    with pytest.raises(ValueError, match="LDAP"):
        validate_context(p, c)


@pytest.mark.parametrize("profile_id", ["fanvil/x3u-pro", "yealink/t46s"])
def test_line_key_needs_no_dial_target(profile_id):
    p, templates = load_bundle(profile_id)
    c = fixture_context()
    c["keys"] = [{"slot": "1", "function": "line", "line": 1, "label": "SIP1"}]
    output = only_output(p, templates, c)
    if p["vendor"] == "fanvil":
        assert ET.fromstring(output).find("./dsskey/internal/Fkey/Value").text == "SIP1"
    else:
        assert "linekey.1.type = 15" in output


@pytest.mark.parametrize("function", ["line", "speed_dial"])
def test_non_dialog_keys_accept_the_core_empty_event_package(function):
    profile, templates = load_bundle("fanvil/x3u-pro")
    context = fixture_context()
    context["keys"][0].update(function=function, event_package="")
    assert only_output(profile, templates, context)


@pytest.mark.parametrize("profile_id", ["fanvil/x3u-pro", "fanvil/x3u", "fanvil/x4u"])
def test_fanvil_phone_parent_keeps_language_and_ldap_together(profile_id):
    """X3U Pro's current projection uses the same phone subtree as X3U/X4U."""
    profile, templates = load_bundle(profile_id)
    context = fixture_context()
    context["keys"] = []
    context["physical"]["language"] = "it"
    context["lines"][0]["expires"] = 300
    context["directory"] = {
        "ldap": {
            "host": "192.0.2.10",
            "port": 1389,
            "base_dn": "ou=phonebook,dc=fixture",
            "bind_dn": "uid=fixture,dc=fixture",
            "password": "fixture-only",
        }
    }
    context["provisioning"] = {"url": "https://example.invalid/provision/"}
    root = ET.fromstring(only_output(profile, templates, context))
    assert root.find("timePlan") is None
    assert root.find("./phone/display/DefaultLanguage").text == "it"
    assert root.find("./phone/ldap/Server").text == "192.0.2.10"
    assert root.find("./phone/ldap/port").text == "1389"
    assert root.find("./phone/ldap/Base").text == "ou=phonebook,dc=fixture"
    assert root.find("./phone/ldap/Username").text == "uid=fixture,dc=fixture"
    assert root.find("./phone/ldap/Password").text == "fixture-only"
    assert root.find("./sip/line/RegisterTTL").text == "300"
    assert root.find("./ap/FlashServerIP").text == context["provisioning"]["url"]
