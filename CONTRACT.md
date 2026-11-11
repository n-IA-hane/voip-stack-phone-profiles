# Catalog contract v1

The integration contains no templates while phone provisioning is disabled.
When enabled, it resolves this repository's `dev` ref to an immutable commit,
fetches `manifest.json`, and fetches only the selected model ZIP. It never
downloads or executes FusionPBX, PHP, Smarty, or Python from a bundle.

`catalog_revision` is SHA256 of canonical UTF-8 JSON (sorted keys, compact
separators, ensure_ascii=false), excluding `catalog_revision` itself.

Each manifest profile has `id`, `vendor`, `family`, `model`, `status`, source
commit and qualification. Only `software_validated` has a `bundle` descriptor
with repository-relative `path`, SHA256 and compressed byte `size`. `imported`
profiles carry a reason and are not servable.

Each ZIP contains `profile.json`, `templates/*.jinja2`, `source/`,
`provenance.json`, `NOTICE` and `LICENSES/MPL-1.1.txt`. Only an `outputs` entry
can be served to a phone. `source/` is provenance, never a provisioning route.
Templates use standard Jinja2, no downloaded helpers. Use a restricted
DictLoader, SandboxedEnvironment, StrictUndefined, XML autoescape for XML,
and no autoescape for CFG. Limit rendered outputs to 256 KiB. Validate format
and an output path whitelist after rendering. Only `{mac}` is allowed in output
paths and expands to twelve lowercase hexadecimal digits.

## Normalized input

- `physical`: required `name`, `mac`; `language` is already the vendor value
  from `capabilities.languages` (BCP47-to-vendor mapping), empty means omit;
  optional `language_code` preserves the canonical UI locale.
- `lines`: objects with integer 1-based `slot`, required `username`, `password`,
  `server`, integer `port`, lowercase `transport` (`udp`, `tcp`, `tls`). Optional
  `auth_username`, `display_name`, `outbound_proxy` default empty; `expires`
  defaults 3600. Empty auth username uses username; empty display name uses
  physical.name; empty expires uses 3600. Empty outbound proxy is omitted.
- `keys`: string numeric `slot`, `function`, required `dial_target` except for
  `line`, integer 1-based `line`, `label`; optional `subscription_target`,
  `pickup_target` default empty; `event_package` defaults `dialog`.
  `line` and `speed_dial` may instead use an empty value, without a subscription.
  Functions are `line`, `speed_dial`, `blf`, `queue_login`, `queue_pause`, `park`.
  This subset supports one common dial/subscription target; differing values
  fail validation. Separate pickup target is mapped only for Yealink.
- `directory.ldap`: `host` (empty means omit), integer `port`, `base_dn`,
  `bind_dn`, `password`, `name_filter`, `number_filter`, `name_attributes`
  (space-separated string), `number_attributes` (space-separated string),
  `display_name` (directory label), optional `display_attribute` defaults
  `displayName`. Default number attributes are `telephonenumber mobile`.
- `provisioning.url`: empty means omit. Only profiles declaring `provision`
  map this field. This never changes firmware, DHCP/PnP switches or intervals.

All strings reject control characters, including CR/LF, before CFG rendering.
Require byte limits before rendering. Never truncate a key target or label.
Keys must refer to an included configured line. Validate optional features
against capabilities. `phone_profiles/render.py` is the original MIT reference
validator/renderer, not code to download and execute in HA.

## Capability and evidence meaning

`max_lines` and `key_slots` bound what the projection can generate. They are
not hardware maxima. Generic profiles use a conservative first-line/first-key
subset where the upstream source demonstrates the parameter structure. Their
`capability_basis` is `upstream_template_subset`. Only vendor-documented values
are named `hardware_max_lines` or `hardware_key_count`.

`software_validated` means compiler, normalized-input rendering, sparse
parameter policy, and XML/CFG validation passed. It does not mean a device has
downloaded/applied it, preserved omitted settings, or passed physical tests.
All current profiles retain `partial_merge_qualification=not_physically_verified`.
The first physical qualification target is Fanvil X3U Pro firmware 2.12.20.

No runtime keypress, call, sound, reboot, reset or PoE action is part of this
contract. HTTP 200 acknowledges transport, not application or a physical effect.
