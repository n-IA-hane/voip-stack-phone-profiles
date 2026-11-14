# Changelog

## Unreleased

- Declare plain LDAP as the supported mode of the current LDAP projections.
- Reject unsupported LDAPS and StartTLS requests before rendering a phone configuration.
- Keep plain LDAP as the compatibility default for existing contexts and profiles.
- Describe the X3U Pro native HTTP application method and exact firmware scope.
- Qualify that method only for X3U Pro firmware 2.12.20 after a real download,
  native readback and continuous-uptime check. The integration still distinguishes
  an accepted request from verified application; other models and firmware remain
  unqualified.
- Record bidirectional native DND synchronization on that device with a fresh
  SIP subscription. Automatic recovery after a PBX restart is not qualified.

Additional LDAP modes require a verified vendor mapping and qualification.
