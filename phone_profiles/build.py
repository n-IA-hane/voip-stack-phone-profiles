# SPDX-License-Identifier: MIT
"""Build deterministic, sparse bundles from pinned local upstream sources."""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

from .render import render
from .smarty import UnsupportedSmarty, compile_template

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "upstream" / "fusionpbx"
SOURCE_COMMIT = "07f0d76acd044e8a07d2f87aeb50bf59f856393b"
FUNCTIONS = ["line", "speed_dial", "blf", "queue_login", "queue_pause", "park"]
NOTICE = """FusionPBX-derived phone configuration templates, Mozilla Public License 1.1.
Original Code: FusionPBX. Its project notice identifies Mark J Crane as Initial Developer.
Upstream commit: 07f0d76acd044e8a07d2f87aeb50bf59f856393b.
Original per-file license notices were absent; project-level license notice is retained.
Modifications by n-IA-hane contributors, 2026-11-11: offline Smarty conversion,
normalized context, sparse parameter projection, explicit capability limits.
Original sources, converted source and modification details are in source/ and
provenance.json in this same bundle. These templates remain under MPL 1.1.
The original tools in phone_profiles/ are separately MIT licensed.
No physical qualification of provisioning or partial-merge behavior is claimed.
"""


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def fixture_context() -> dict:
    """Synthetic, non-device fixture, never sent to a phone."""
    return {
        "physical": {"name": "Software fixture", "mac": "020000000001", "language": ""},
        "lines": [
            {
                "slot": 1,
                "username": "fixture480",
                "password": "fixture-not-a-device-secret",
                "server": "192.0.2.10",
                "port": 5060,
                "transport": "udp",
            }
        ],
        "keys": [{"slot": "1", "function": "blf", "dial_target": "430", "line": 1, "label": "P4"}],
    }


def projection(vendor: str, model: str, source: str, related: str = "") -> tuple[str, dict, str]:
    """Select a family mapping only if its required parameter names exist upstream."""
    keys = False
    functions = ["sip_account"]
    languages = {}
    if vendor == "fanvil":
        required = ["<sysConf", "<PhoneNumber>", "<RegisterAddr>", "<RegisterPswd>", "<Transport>"]
        if not all(x in source for x in required):
            raise UnsupportedSmarty("Fanvil sparse XML account mapping unavailable")
        name = "fanvil.xml.jinja2"
        text = (ROOT / "templates" / name).read_text()
        parent = "timePlan" if "<timePlan>" in source else "phone"
        if f"<{parent}>" not in source:
            raise UnsupportedSmarty("Fanvil phone settings parent unavailable")
        if model == "x3u-pro":
            # X3U Pro 2.12 uses the phone settings parent shared by X3U/X4U.
            # Preserve its original FusionPBX timePlan source as provenance.
            parent = "phone"
        text = text.replace("__PHONE_PARENT__", parent)
        keys = "<Fkey index=" in source and '<internal index="1">' in source
        if keys:
            functions.extend(FUNCTIONS)
        if '<ldap index="1">' in source:
            functions.append("ldap")
        if "<DefaultLanguage>en</DefaultLanguage>" in source:
            languages = {"en": "en", "it": "it"}
            functions.append("language")
        if "<FlashServerIP>" in source:
            functions.append("provision")
    elif vendor == "yealink":
        required = [".auth_name", ".user_name", ".password", ".sip_server."]
        if not all(x in source for x in required):
            raise UnsupportedSmarty("Yealink sparse account mapping unavailable")
        name = "yealink.cfg.jinja2"
        text = (ROOT / "templates" / name).read_text()
        # Modern Yealink splits account and DSS settings between MAC and
        # model-common CFG files. Only already-converted related sources count.
        keys = bool(
            re.search(r"^linekey\..+\.(?:type|value)\s*=", source + "\n" + related, re.MULTILINE)
        )
        if keys:
            functions.extend(FUNCTIONS)
    elif vendor == "snom":
        if not all(x in source for x in ("<user_name", "<user_pass", "<user_host")):
            raise UnsupportedSmarty("Snom sparse identity mapping unavailable")
        name = "snom.xml.jinja2"
        text = (ROOT / "templates" / name).read_text()
        keys = "<fkey " in source
        if keys:
            functions.extend(FUNCTIONS)
    elif vendor == "grandstream":
        if '.sip.subscriber.password"' in source:
            name = "grandstream.xml.jinja2"
            required = [
                ".sip.userid",
                ".sip.subscriber.userid",
                ".sip.subscriber.name",
                ".sip.transport",
            ]
            if not all(x in source for x in required):
                raise UnsupportedSmarty("Grandstream named account mapping incomplete")
            keys = all(
                x in source for x in ("pks.vpk.", ".keyMode", ".account", ".description", ".value")
            )
            if keys:
                functions.extend([f for f in FUNCTIONS if f != "line"])
        elif all(f"<P{p}>" in source for p in (271, 270, 47, 35, 36, 34, 3, 183)):
            name = "grandstream-pvalues.xml.jinja2"
        else:
            raise UnsupportedSmarty("Grandstream sparse account mapping unavailable")
        text = (ROOT / "templates" / name).read_text()
    else:
        raise UnsupportedSmarty("unknown vendor family")
    # Limits describe what this projection emits, not the physical hardware maximum.
    max_lines = 6 if (vendor, model) == ("fanvil", "x3u-pro") else 1
    max_keys = 3 if (vendor, model) == ("fanvil", "x3u-pro") else int(keys)
    caps = {
        "max_lines": max_lines,
        "key_slots": [
            {
                "slot": str(i),
                "max_value_bytes": 31 if vendor == "fanvil" else 64,
                "max_label_bytes": 16,
                "functions": [f for f in functions if f in FUNCTIONS],
            }
            for i in range(1, max_keys + 1)
        ],
        "functions": functions,
        "languages": languages,
        "capability_basis": "vendor_documentation_and_local_UI_limits"
        if max_lines == 6
        else "upstream_template_subset",
        "limit_semantics": "maximum_generated_by_this_projection_not_hardware_maximum",
        "separate_subscription_target": False,
        "separate_pickup_target": vendor == "yealink",
        "projection_qualification": "software_only",
        "partial_merge_qualification": "not_physically_verified",
    }
    if max_lines == 6:
        caps.update(
            hardware_max_lines=6,
            hardware_key_count=3,
            evidence=[
                "https://www.fanvil.com/upload/files/20220518/13428ft422.pdf",
                "Local X3U Pro 2.12.20 DSS value input maxlength=31, 2026-11-11",
            ],
        )
    return text, caps, "cfg" if vendor == "yealink" else "xml"


def deterministic_zip(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    # Stored members are byte-reproducible across Python/zlib versions. A model
    # bundle remains bounded (the current largest is below 2 MiB), fetched once.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(2026, 11, 11, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def build() -> dict:
    provenance = json.loads((ROOT / "provenance" / "fusionpbx.json").read_text())
    notices = (ROOT / "provenance" / "upstream-project-notice.txt").read_bytes()
    license_text = (ROOT / "LICENSES" / "MPL-1.1.txt").read_bytes()
    env = Environment(undefined=StrictUndefined, extensions=["jinja2.ext.loopcontrols"])
    profiles = []
    conversion_report = []
    converted = {}
    for source in sorted(UPSTREAM.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(UPSTREAM).as_posix()
        raw = source.read_bytes()
        if not any(
            r["path"].endswith("/" + rel) and r["sha256"] == sha256(raw).hexdigest()
            for r in provenance["files"]
        ):
            raise ValueError(f"upstream hash mismatch: {rel}")
        try:
            jinja = compile_template(raw.decode("utf-8-sig"))
            env.parse(jinja)
            converted[rel] = jinja
            out = ROOT / "converted" / (rel + ".jinja2")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                "{# SPDX-License-Identifier: MPL-1.1; see NOTICE and provenance.json #}\n" + jinja
            )
            conversion_report.append({"path": rel, "status": "converted"})
        except (UnsupportedSmarty, TemplateSyntaxError) as exc:
            # Report only source syntax, not rendered credentials.
            conversion_report.append({"path": rel, "status": "imported", "reason": str(exc)[:180]})
    # Each directory is one model/family profile; aliases and auxiliary files are source only.
    parents = sorted({p.parent for p in UPSTREAM.rglob("*") if p.is_file() and "{$mac}" in p.name})
    for parent in parents:
        rel_parent = parent.relative_to(UPSTREAM).as_posix()
        vendor, model = rel_parent.split("/", 1)
        candidates = sorted(
            [p for p in parent.iterdir() if p.is_file() and "{$mac}" in p.name],
            key=lambda p: (not p.name.startswith("{$mac}"), p.suffix != ".cfg", p.name),
        )
        source = candidates[0]
        rel = source.relative_to(UPSTREAM).as_posix()
        profile = {
            "schema_version": 1,
            "id": rel_parent,
            "vendor": vendor,
            "family": vendor,
            "model": model,
            "status": "imported",
            "capabilities": {
                "max_lines": 0,
                "key_slots": [],
                "functions": [],
                "languages": {},
                "capability_basis": "not_validated",
            },
            "source_commit": SOURCE_COMMIT,
            "qualification": {
                "software": False,
                "physical": False,
                "partial_merge": "not_physically_verified",
            },
        }
        try:
            if rel not in converted:
                reason = next(r["reason"] for r in conversion_report if r["path"] == rel)
                raise UnsupportedSmarty(reason)
            related = "\n".join(
                converted[p.relative_to(UPSTREAM).as_posix()]
                for p in parent.iterdir()
                if p.is_file() and p.relative_to(UPSTREAM).as_posix() in converted and p != source
            )
            template, caps, fmt = projection(
                vendor, model, source.read_text(encoding="utf-8-sig"), related
            )
            profile["capabilities"] = caps
            filename = source.name.replace("{$mac}", "{mac}")
            profile["outputs"] = [
                {"path": filename, "template": "templates/config.jinja2", "format": fmt}
            ]
            profile["managed_sections"] = ["sip_accounts", "keys"] + [
                f for f in ("language", "ldap", "provision") if f in caps["functions"]
            ]
            profile["merge_verification"] = "not_physically_verified"
            context = fixture_context()
            if not caps["key_slots"]:
                context["keys"] = []
            render(profile, {"templates/config.jinja2": template}, context)
            profile["status"] = "software_validated"
            profile["qualification"]["software"] = True
            files = {
                "profile.json": canonical(profile),
                "templates/config.jinja2": template.encode(),
                "LICENSES/MPL-1.1.txt": license_text,
                "NOTICE": NOTICE.encode(),
                "source/upstream-project-notice.txt": notices,
                "source/full-conversion.jinja2": converted[rel].encode(),
            }
            file_provenance = []
            for p in sorted(parent.rglob("*")):
                if not p.is_file():
                    continue
                relative = p.relative_to(UPSTREAM).as_posix()
                data = p.read_bytes()
                files["source/original/" + p.relative_to(parent).as_posix()] = data
                row = next(r for r in provenance["files"] if r["path"].endswith("/" + relative))
                file_provenance.append(row)
            profile_provenance = {
                "schema_version": 1,
                "upstream_repository": "fusionpbx/fusionpbx",
                "upstream_commit": SOURCE_COMMIT,
                "files": file_provenance,
                "modifications": [
                    {
                        "date": "2026-11-11",
                        "author": "n-IA-hane contributors",
                        "description": "Offline Smarty conversion and sparse normalized-context projection; unrelated vendor defaults omitted.",
                    }
                ],
            }
            if (vendor, model) == ("fanvil", "x3u-pro"):
                profile_provenance["modifications"].append(
                    {
                        "date": "2026-11-12",
                        "author": "n-IA-hane contributors",
                        "description": "Use phone rather than timePlan for X3U Pro 2.12 language and LDAP settings; retain the original upstream source unchanged.",
                    }
                )
            files["provenance.json"] = canonical(profile_provenance)
            blob = deterministic_zip(files)
            path = "bundles/" + rel_parent + ".zip"
            out = ROOT / path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(blob)
            profile["bundle"] = {
                "path": path,
                "sha256": sha256(blob).hexdigest(),
                "size": len(blob),
            }
        except UnsupportedSmarty as exc:
            profile["status"] = "imported"
            profile["qualification"]["software"] = False
            profile["reason"] = str(exc)[:180]
            profile.pop("bundle", None)
        profiles.append(profile)
    manifest = {
        "schema_version": 1,
        "upstream": {"repository": "fusionpbx/fusionpbx", "commit": SOURCE_COMMIT},
        "profiles": profiles,
    }
    manifest["catalog_revision"] = sha256(canonical(manifest)).hexdigest()
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    report = {
        "source_files": len(conversion_report),
        "conversion": dict(Counter(r["status"] for r in conversion_report)),
        "profiles": dict(Counter(p["status"] for p in profiles)),
        "files": conversion_report,
    }
    (ROOT / "provenance" / "conversion-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return {k: v for k, v in report.items() if k != "files"}


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True), flush=True)
