# Configurable roles with two System Roles

Roles became an assignable entity rather than a fixed `admin|member` field. A User holds exactly one Role by identity; two System Roles — Administrator and Member — are seeded with fixed identities and cannot be deactivated or deleted, while administrators may create further Roles as assignment labels. Authorization still has exactly one privileged role: holding the Administrator System Role, checked by identity rather than title, so renaming a Role never changes access. This supersedes ADR-0003: we kept per-role hardcoded rules and did not build a permission/ACL system, because the requirement's "roles and permissions" is satisfied by manageable role entities whose only capability boundary is Administrator versus everyone else.

Custom Roles therefore convey no capabilities — they organise Users but grant nothing. A future permission or grant model would be a separate, deliberate decision.

Status: Accepted; supersedes ADR-0003.
