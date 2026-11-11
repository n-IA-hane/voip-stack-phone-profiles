# SPDX-License-Identifier: MIT
"""Explicit offline import from a fixed upstream commit, never run by Home Assistant."""

from __future__ import annotations

from hashlib import sha1, sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile

from .build import ROOT, SOURCE_COMMIT

FAMILIES = {"fanvil", "yealink", "snom", "grandstream"}
ARCHIVE_SHA256 = "a51ba316dc0cb1f8524da1d65699f1281732f5b62827feea3b6802fff75f7628"
EXCLUDED = {
    "resources/templates/provision/grandstream/gds3710/{$mac}.xml": "static TLS private key",
    "resources/templates/provision/grandstream/gxp2160/gxp2160_labels.ott": "binary OpenDocument label asset",
}


def import_archive(data: bytes, root: Path) -> dict:
    """Read members without tar extraction; only validated UTF-8 regular files are copied."""
    if sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("pinned upstream archive hash mismatch; no files written")
    rows = []
    with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            path = member.name.split("/", 1)[-1]
            prefix = "resources/templates/provision/"
            if path == "resources/licenses.php" and member.isfile():
                text = archive.extractfile(member).read().decode()
                text = text[text.index("FusionPBX License") : text.index("3rd Party Licenses")]
                target = root / "provenance" / "upstream-project-notice.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    text.replace(
                        "//-----------------------------------------------------------------------------------",
                        "",
                    ).strip()
                    + "\n"
                )
            if not path.startswith(prefix):
                continue
            relative = path[len(prefix) :]
            if relative.split("/", 1)[0] not in FAMILIES or path in EXCLUDED:
                continue
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("non-regular catalog source")
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise ValueError("unsafe source path")
            raw = archive.extractfile(member).read()
            raw.decode("utf-8-sig")
            if b"\0" in raw or b"PRIVATE KEY-----" in raw:
                raise ValueError("non-text or private-key material in source")
            destination = root / "upstream" / "fusionpbx" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            rows.append(
                {
                    "path": path,
                    "sha256": sha256(raw).hexdigest(),
                    "git_blob_sha1": sha1(
                        b"blob " + str(len(raw)).encode() + b"\0" + raw
                    ).hexdigest(),
                    "size": len(raw),
                    "file_notice": "absent",
                    "license_basis": "upstream_project_notice",
                    "upstream_project_license": "MPL-1.1",
                }
            )
    if len(rows) != 612:
        raise ValueError("fixed upstream file inventory changed")
    result = {
        "schema_version": 1,
        "repository": "fusionpbx/fusionpbx",
        "commit": SOURCE_COMMIT,
        "archive_sha256": sha256(data).hexdigest(),
        "files": sorted(rows, key=lambda r: r["path"]),
        "excluded": [{"path": p, "reason": reason} for p, reason in sorted(EXCLUDED.items())],
    }
    target = root / "provenance" / "fusionpbx.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    archive = subprocess.check_output(
        ["gh", "api", f"repos/fusionpbx/fusionpbx/tarball/{SOURCE_COMMIT}"]
    )
    inventory = import_archive(archive, ROOT)
    print(json.dumps({"files": len(inventory["files"]), "commit": SOURCE_COMMIT}))
