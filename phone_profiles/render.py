# SPDX-License-Identifier: MIT
"""Reference implementation of the public, vendor-independent bundle contract."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any

from jinja2 import DictLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

MAX_OUTPUT_BYTES = 256 * 1024


def normalized_context(context: dict[str, Any]) -> dict[str, Any]:
    """Fill only documented optional fields; required values remain required."""
    c = deepcopy(context)
    p = c.setdefault("physical", {})
    p.setdefault("language", "")
    p.setdefault("language_code", "")
    c.setdefault("lines", [])
    c.setdefault("keys", [])
    retired = c.setdefault("retired", {})
    if not isinstance(retired, dict) or set(retired) - {"keys", "lines"}:
        raise ValueError("invalid_retired_slots")
    for kind in ("keys", "lines"):
        retired.setdefault(kind, [])
    for line in c["lines"]:
        for key, default in {
            "auth_username": "",
            "display_name": "",
            "expires": 3600,
            "outbound_proxy": "",
        }.items():
            line.setdefault(key, default)
    for key in c["keys"]:
        for field, default in {
            "dial_target": "",
            "subscription_target": "",
            "pickup_target": "",
            "event_package": "dialog",
            "label": "",
        }.items():
            key.setdefault(field, default)
    ldap = c.setdefault("directory", {}).setdefault("ldap", {})
    for key, default in {
        "host": "",
        "port": 389,
        "base_dn": "",
        "bind_dn": "",
        "password": "",
        "name_filter": "",
        "number_filter": "",
        "name_attributes": "cn sn displayName",
        "number_attributes": "telephonenumber mobile",
        "display_name": "LDAP",
        "display_attribute": "displayName",
    }.items():
        ldap.setdefault(key, default)
    c.setdefault("provisioning", {}).setdefault("url", "")
    return c


def validate_context(profile: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Validate projection bounds before rendering; never trim a route or label."""
    c = normalized_context(context)
    caps = profile["capabilities"]
    if not re.fullmatch(r"[0-9a-f]{12}", c["physical"]["mac"]):
        raise ValueError("physical.mac must be twelve lowercase hex digits")

    def strings(value: Any) -> None:
        if isinstance(value, str) and any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("control character in configuration input")
        if isinstance(value, dict):
            for item in value.values():
                strings(item)
        elif isinstance(value, list):
            for item in value:
                strings(item)

    strings(c)
    slots = []
    for line in c["lines"]:
        slot = line["slot"]
        if type(slot) is not int or not 1 <= slot <= caps["max_lines"] or slot in slots:
            raise ValueError("line slot outside the projection or duplicated")
        slots.append(slot)
        if not line["username"] or not line["password"] or not line["server"]:
            raise ValueError("SIP username, password and server are required")
        if type(line["port"]) is not int or not 1 <= line["port"] <= 65535:
            raise ValueError("invalid SIP port")
        if line["transport"] not in ("udp", "tcp", "tls"):
            raise ValueError("unsupported SIP transport")
        if profile["vendor"] == "snom" and line["auth_username"] not in ("", line["username"]):
            raise ValueError("this Snom subset requires auth username equal to SIP username")
    key_caps = {k["slot"]: k for k in caps["key_slots"]}
    seen = set()
    for key in c["keys"]:
        slot = key["slot"]
        if slot not in key_caps or slot in seen:
            raise ValueError("unknown or duplicated key slot")
        seen.add(slot)
        bound = key_caps[slot]
        if key["function"] not in bound["functions"]:
            raise ValueError("unsupported key function")
        if type(key["line"]) is not int or key["line"] not in slots:
            raise ValueError("key must reference a configured line")
        for name in ("dial_target", "subscription_target", "pickup_target"):
            if len(key.get(name, "").encode()) > bound["max_value_bytes"]:
                raise ValueError("key target exceeds byte limit")
        if len(key["label"].encode()) > bound["max_label_bytes"]:
            raise ValueError("key label exceeds byte limit")
        if key["function"] != "line" and not key["dial_target"]:
            raise ValueError("key dial target is required")
        if key["subscription_target"] and key["subscription_target"] != key["dial_target"]:
            raise ValueError("this subset requires one common dial and subscription target")
        dialog_key = key["function"] in {"blf", "queue_login", "queue_pause", "park"}
        if key["event_package"] != "dialog" and (dialog_key or key["event_package"] != ""):
            raise ValueError("only dialog subscriptions are mapped; non-dialog keys may be empty")
        if key["pickup_target"] and profile["vendor"] != "yealink":
            raise ValueError("separate pickup target is not mapped for this subset")
    for kind, allowed, active, feature in (
        ("keys", set(key_caps), seen, "clear_keys"),
        (
            "lines",
            {str(slot) for slot in range(1, caps["max_lines"] + 1)},
            {str(slot) for slot in slots},
            "disable_lines",
        ),
    ):
        retired = c["retired"][kind]
        if (
            not isinstance(retired, list)
            or any(
                not isinstance(slot, str)
                or not re.fullmatch(r"[1-9][0-9]*", slot)
                or slot not in allowed
                for slot in retired
            )
            or len(set(retired)) != len(retired)
        ):
            raise ValueError(f"invalid_retired_{kind}")
        if set(retired) & active:
            raise ValueError(f"retired_{kind}_still_active")
        if retired and caps.get(feature, False) is not True:
            raise ValueError(f"profile_{feature}_unsupported")
    if c["physical"]["language"] not in ("", *caps["languages"].values()):
        raise ValueError("language has no declared vendor mapping")
    if c["directory"]["ldap"]["host"] and "ldap" not in caps["functions"]:
        raise ValueError("LDAP is not mapped for this subset")
    if c["provisioning"]["url"] and "provision" not in caps["functions"]:
        raise ValueError("provisioning URL is not mapped for this subset")
    return c


def render(
    profile: dict[str, Any], templates: dict[str, str], context: dict[str, Any]
) -> dict[str, bytes]:
    c = validate_context(profile, context)
    result = {}
    for output in profile["outputs"]:
        path = output["path"].format(mac=c["physical"]["mac"])
        if not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise ValueError("unsafe output path")
        env = SandboxedEnvironment(
            loader=DictLoader(templates),
            undefined=StrictUndefined,
            autoescape=output["format"] == "xml",
            keep_trailing_newline=True,
        )
        data = env.get_template(output["template"]).render(c).encode()
        if len(data) > MAX_OUTPUT_BYTES:
            raise ValueError("rendered output exceeds limit")
        if output["format"] == "xml":
            ET.fromstring(data)
        elif output["format"] == "cfg":
            for line in data.decode().splitlines():
                if line.strip() and not line.lstrip().startswith(("#", ";")) and "=" not in line:
                    raise ValueError("invalid CFG record")
        else:
            raise ValueError("unsupported output format")
        result[path] = data
    return result
