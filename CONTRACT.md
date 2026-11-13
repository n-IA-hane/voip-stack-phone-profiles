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
  optional `language_code` preserves the canonical UI locale. Optional
  `time_zone` is an IANA identifier, default empty means omit clock settings.
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
- `retired`: optional mapping containing `keys` and `lines`, each a list of
  canonical positive decimal slot strings. Missing lists default to empty,
  preserving version 1 callers. Slots must be declared by the profile, unique,
  and absent from the active `keys`/`lines` in this revision. A retired key does
  not require an active line or account credentials. Unknown fields and slots
  fail validation. The HA provisioning ledger, not a template, establishes
  historical ownership before supplying these intents.
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

## Optional clock mapping

`capabilities.time_zones` maps supported IANA identifiers to vendor clock data.
An absent or empty mapping supports only an empty `physical.time_zone`.
For a nonempty zone, validation requires exact membership and derives `clock`
from that declared mapping, replacing any caller-supplied `clock`. The data
fields are `code`, `name`, `dst_type` and `dst_location`. Templates use
`clock|default({})` so older version 1 renderers omit the optional block.

Only Fanvil X3U Pro currently declares mappings: `Europe/Rome` uses base
UTC+1 (quarter-hour code4) and automatic DST for Rome locality13; `UTC` and
`Etc/UTC` use code0 with DST disabled. The generated `phone/date` block contains
only `TimeZone`, `TimeZoneName`, `DSTType` and `DSTLocation`. It does not change
NTP servers, date format, manual DST rules or the current time directly.
The base offset remains UTC+1 in summer; the phone applies DST separately.

This is a deliberately partial, extensible mapping, not support for every HA
time zone or every phone model. Unsupported zones fail validation rather than
being guessed from a current UTC offset. Rome locality and mode come from
read-only X3U Pro 2.12.20 options; provisioning application remains separately
qualified. Empty time zones preserve the existing generated configuration.

## Owned slot retirement

Every profile declares boolean `clear_keys` and `disable_lines` capabilities.
An absent flag is false for older profiles. Nonempty retired lists require the
corresponding flag to be exactly true. A documented allowlist covers Fanvil
X3U Pro, Snom 720/7xx and Yealink T42U/T43U/T46G/T46S/T46U. Other profiles,
including all current Grandstream projections, retain positive configuration
support while removals remain unsupported. `retirement_evidence` and
`retirement_qualification` distinguish documented commands from the Fanvil
source-based candidate; neither is a physical application acknowledgement.

Only the requested slots are emitted. There is no full-device reset, blanket
key list replacement, boot default change or takeover of unknown slots.

- Yealink keys use explicit `type = 0` (N/A), with `%NULL%` for the value,
  label and extension strings. `%NULL%` resets a parameter to its documented
  default, which is empty for these strings. It must never reset the key type,
  whose factory default can be Line (15). Retired lines use `enable = 0` and
  reset `user_name`, `auth_name` and `password` to their empty defaults.
- Snom keys use `none` under the `functionKeys` sibling of `phone-settings`;
  retired identities use `user_active = off`. Active keys use numeric,
  one-based identity context, while function key indices remain zero-based.
- Fanvil keys use `Type = 0` with empty `Value` and `Title`; retired lines use
  `EnableReg = 0`. Snom and Fanvil line disabling does not claim erasure of
  stored credentials. Sparse clearing on X3U Pro 2.12.20 remains a candidate
  until independently qualified on the device.

Retirement commands are idempotent. The caller must retain a tombstone until
the slot is reused or its removal is independently acknowledged. Download of
a configuration, SIP registration and a prepared file are distinct states;
none alone proves application. Existing phones without an ownership history
must not infer old slots from the profile's total capacity.

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
