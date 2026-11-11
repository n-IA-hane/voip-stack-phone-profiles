# VoIP Stack phone profiles

Optional, versioned phone provisioning assets for VoIP Stack. The integration
fetches this catalog from its own repository only when the feature is enabled,
then downloads just the selected model bundle at an immutable repository commit.
No templates or bundles are required by the integration while the feature is off.

This repository is prepared for the `dev` branch. A local build is not a
publication, Home Assistant deployment, or phone provisioning action.

## Catalog and evidence

The four imported families are Fanvil, Yealink, Snom and Grandstream, from
FusionPBX commit `07f0d76acd044e8a07d2f87aeb50bf59f856393b`.
The complete retained inventory has 612 UTF-8 files with per-file SHA256 and
Git blob SHA1 in [provenance/fusionpbx.json](provenance/fusionpbx.json).

Two upstream files are deliberately absent:

- Grandstream GDS3710's MAC XML contains a static TLS private key.
- GXP2160's OpenDocument label template is not a text provisioning asset.

No firmware, logos, sounds or fonts are imported. URLs or vendor fields in an
original source do not authorize fetching those other assets or writing those
settings. The sparse output templates omit network/DNS, administrator passwords,
volume, codecs and firmware settings entirely.

[manifest.json](manifest.json) lists every imported model/family profile.
`imported` profiles are visible with a reason but have no downloadable bundle.
`software_validated` profiles passed compilation of the used Smarty source,
normalized-input rendering, output-format and sparse-parameter tests. This is
not a physical provisioning or partial-merge guarantee. Unknown constructs fail
closed, never turn into missing credentials or silently blank output.

Generic profiles deliberately expose a conservative first-line/first-key
projection where the source demonstrates the mapping. These are software
projection limits, not a claim about hardware capacity. X3U Pro declares six
lines and three physical keys from its official datasheet, with a 31-byte target
limit from the observed firmware UI. It is the first intended physical test
target, not the only model users may select.

## Build and verify

Use Python 3.12 or newer in an environment with Jinja2 and pytest:

```sh
python -m phone_profiles.build
python -m pytest -q
```

The normal build is offline. It reads retained originals, records conversion
results, emits canonical metadata and deterministic ZIP files, and never contacts
a phone, HA, a provisioning server, or a SIP endpoint.

An explicit maintainer-only re-import uses the authenticated GitHub CLI and the
fixed upstream commit, without cloning or extracting a tar archive:

```sh
python -m phone_profiles.import_fusionpbx
```

The shared compiler supports its documented Smarty subset, including conditionals,
`isset`, PHP false values including `"0"`, loops, assignment, literal/strip blocks
and selected modifiers. It does not run PHP/Smarty. The seven-sample differential
tests compare effective fields against pinned original expressions plus explicit
expected values. They do not claim execution in the upstream PHP Smarty engine.

## Integration contract

See [CONTRACT.md](CONTRACT.md). Only declared `outputs` may be served to a phone.
`source/`, notices and licenses in a ZIP are included for provenance and source
availability. They are never provisioning endpoints. Templates accept the common
physical/lines/keys/directory context; no vendor Python is downloaded into HA.

Fetch, applied configuration, live SIP registration, BLF behavior and physical
keypress behavior are different evidence levels. HTTP 200 does not prove an
action occurred. Physical testing requires its own explicit test session and
independent LCD/SIP/HA observations. Provisioning never invokes test calls, keys,
reboots, resets, audio or PoE automatically.

## Licenses

Original tooling is MIT. Imported and derived template source remains MPL 1.1.
See [LICENSE](LICENSE), [NOTICE](NOTICE), [MPL 1.1](LICENSES/MPL-1.1.txt), and the
upstream project notice. Per-file notices were absent upstream; this is recorded,
not treated as public-domain status. Source and dated modification information
are included in each model bundle. Asset distribution does not relicense the
integration core or its original tools.
