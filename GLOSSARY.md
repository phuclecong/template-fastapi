# Template Dashboard

A single-tenant, authenticated dashboard: users manage a shared task board.

## Language

**User**:
A person with an account in the dashboard, identified by a unique, case-insensitive email. Each user holds exactly one Role.
_Avoid_: Account, member record

**Role**:
A named capability level a User holds. The Administrator System Role grants workspace administration; the Member System Role is the default for new Users. Administrators may create further Roles, but only the Administrator System Role grants administration.
_Avoid_: Permission, privilege, group

**System Role**:
One of the two built-in Roles — Administrator and Member — that the workspace can neither deactivate nor delete. Their identities are fixed; their titles are display labels.
_Avoid_: Fixed role, built-in role

**Role status**:
Whether a Role is `active` (assignable to Users) or `inactive` (kept for its current holders, but no longer assignable).
_Avoid_: Enabled/disabled, archived

**Task**:
A unit of work on the shared board, with a title, an optional description, priority, due date, and assignee, and a status.
_Avoid_: Ticket, item, card

**Assignee**:
The user responsible for a task; may be unassigned. A non-administrator may update or delete only tasks assigned to them, and may change the assignee only on a task they already own.
_Avoid_: Owner, handler

**Task status**:
A task's position in its lifecycle: `todo`, `in-progress`, `done`, or `blocked`. Moves `todo → in-progress → done`; `blocked` is set from `todo` or `in-progress` and clears back to the prior state. A task enters the board at `todo` (or `in-progress`/`blocked`), never `done`.
_Avoid_: State, phase

**Priority**:
A task's importance: `low`, `medium`, or `high`; may be unset.
_Avoid_: Severity, urgency

**Dashboard**:
The workspace-wide summary of Tasks: totals, status and priority distributions, and the busiest assignees.
_Avoid_: Overview, home, analytics

**Session**:
An authenticated login. Revoked on logout; holds the refresh credential.
_Avoid_: Login, auth record

**Access token**:
The credential that authenticates a request as a given user.
_Avoid_: Bearer token, auth token

**Refresh token**:
The credential used to obtain a new access token. Rotated on each use; the old one stops working.
_Avoid_: Renewal token
