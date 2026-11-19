# Changelog

## Unreleased

- Configure any of the twelve built-in keys and twelve SIP identities on the
  Snom 360. Clearing a managed key or removing a managed line leaves the
  other positions intact. One SIP line can serve all twelve keys.
- Give Snom desk phones the exact settings file for manual setup, DHCP and SIP
  Plug and Play. The 360 stores the file URL and requests an hourly refresh.
  Its firmware 8.7.3.25.9 profile declares the documented SIP configuration
  refresh request. Physical application on this firmware still needs verification.
- Serve `cfg{mac}.xml` for Grandstream hardware boot downloads and retain
  the existing `{mac}.xml` link. GRP26xx phones receive a complete file URL
  through SIP Plug and Play and use a directory for DHCP or manual setup.
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
