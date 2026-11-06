# Spec: Template Dashboard API

## Problem Statement

A developer starting a new authenticated dashboard app has to hand-assemble the same backend every time: registration and login with tokens, a two-role user model, a task board with filtering/sorting/pagination, and password handling. There is no single, contract-first FastAPI implementation to copy.

## Solution

Implement the **Template Dashboard API** as a FastAPI service that conforms exactly to the OpenAPI contract in `docs/openapi.yaml`. The service exposes versioned JSON APIs under `/api/v1`, generates its OpenAPI schema from the code, and keeps it in sync with the contract that drives the frontend MSW/TypeScript layer. It is a single-tenant dashboard: one user pool, one task board, two fixed roles (`admin`, `member`).

## User Stories

### Authentication

1. As a visitor, I want to register with a name, email, and password, so that I can get an account.
2. As a visitor, I want my email to be treated case-insensitively (lowercased) at registration, so that `Alice@X.com` and `alice@x.com` are the same account.
3. As a visitor, I want a clear 409 when my email is already taken, so that I know to log in instead.
4. As a visitor, I want registration to return access and refresh tokens plus my user, so that I'm signed in immediately.
5. As a visitor, I want to log in with email and password, so that I can start a session.
6. As a visitor, I want a 401 on a wrong email or password, so that failed logins are indistinguishable but rejected.
7. As an authenticated user, I want to exchange my refresh token for a new access token, so that I stay signed in without re-entering my password.
8. As an authenticated user, I want refresh to rotate the refresh token (and reject reuse of a stale one), so that a stolen refresh token is detected.
9. As an authenticated user, I want logout to revoke my session, so that the refresh token stops working.
10. As a registrant, I want my account created with the `member` role, so that only admins grant elevated access.

### Users & roles

11. As an authenticated user, I want to fetch my own profile (`GET /users/me`), so that the client can rehydrate my session without a full login.
12. As a member, I want to list all users in the workspace, so that I can pick an assignee for a task.
13. As an admin, I want to list all users with pagination, so that the user management screen scales.
14. As an admin, I want to change another user's role between `admin` and `member`, so that I can grant or revoke admin access.
15. As an admin, I want a guard that prevents demoting or deleting the last admin, so that the workspace can never be left admin-less.
16. As an admin, I want to delete a user, so that I can remove someone from the workspace.
17. As an admin, I want deleting a user to leave their tasks unassigned (not delete them), so that no work is silently lost.
18. As an admin, I want to be unable to delete my own account, so that deletion always goes through another admin.
19. As an admin, I want to create the first admin via a deterministic seed (env var), so that a fresh deploy is not locked out.

### Tasks — creation & editing

20. As an authenticated user, I want to create a task with just a title, so that I can capture work quickly.
21. As an authenticated user, I want to create a task with optional description, status, priority, assignee, and due date, so that I can capture full detail up front.
22. As an authenticated user, I want a new task to default to `todo`, so that tasks don't appear in arbitrary states.
23. As an authenticated user, I want to be able to create a task directly in `in-progress` or `blocked`, but not `done`, so that `done` is only ever reached by a transition.
24. As a member, I want to edit a task I am assigned to, so that I can keep my work current.
25. As a member, I want to be forbidden (403) from editing a task assigned to someone else, so that tasks are owned by their assignee.
26. As a member, I want to reassign or unassign my own tasks, so that I can hand work off.
27. As a member, I want to be unable to acquire someone else's task by setting its assignee to myself, so that self-assignment can't bypass ownership.
28. As an admin, I want to edit or reassign any task, so that I can keep the board correct.
29. As an authenticated user, I want to update a single field without touching others, so that partial updates are safe.
30. As an authenticated user, I want an explicit `null` to clear an optional field (unassign, clear due date), so that clearing is unambiguous.
31. As an authenticated user, I want to move a task through `todo → in-progress → done`, so that status reflects real progress.
32. As an authenticated user, I want to mark a task `blocked` from `todo` or `in-progress`, so that I can flag a dependency.
33. As an authenticated user, I want unblocking a task to return it to its prior state, so that the pause is reversible.
34. As a member, I want to delete a task I am assigned to, so that I can remove my own work.
35. As a member, I want to be forbidden (403) from deleting someone else's task, so that ownership is respected.
36. As an authenticated user, I want to fetch a single task by id, so that the client can deep-link to it.
37. As an authenticated user, I want a 404 for a task id that doesn't exist, so that missing resources are clear.

### Tasks — listing, filtering, sorting, pagination

38. As an authenticated user, I want to list all tasks, so that I can see the whole board.
39. As an authenticated user, I want to filter tasks by a case-insensitive substring on the title (`q`), so that I can search.
40. As an authenticated user, I want to filter by status, so that I can see only what's `todo`, `in-progress`, `done`, or `blocked`.
41. As an authenticated user, I want to filter by priority, so that I can triage by importance.
42. As an authenticated user, I want to filter by assignee (or the literal `unassigned`), so that I can see a person's workload.
43. As an authenticated user, I want to filter by due-date range (`dueDate_gte`/`dueDate_lte`), so that I can see what's due soon.
44. As an authenticated user, I want to paginate with `_start`/`_end`, so that I don't fetch the whole board at once.
45. As an authenticated user, I want an `x-total-count` header with the total matching count, so that the client can render "N of M".
46. As an authenticated user, I want to sort by `title`, `status`, `priority`, or `dueDate`, so that I can order the board my way.
47. As an authenticated user, I want `asc`/`desc` control, so that sorting direction is explicit.
48. As an authenticated user, I want enum fields (`status`, `priority`) to sort in their declared order, so that sorting is meaningful rather than alphabetical.

### Bulk update

49. As an authenticated user, I want to update status, priority, and/or assignee across many tasks in one request, so that I can batch triage.
50. As a member, I want bulk update to apply only to my own tasks and report per-id failures for the rest, so that a mixed batch is safe and transparent.
51. As an authenticated user, I want a bulk response reporting the count updated and the per-id failures, so that I can act on what didn't apply.

### Password

52. As an authenticated user, I want to update my password by providing my current password, so that I can rotate credentials.
53. As an authenticated user, I want a wrong current password to be rejected (400), so that only the account holder can change it.
54. As an authenticated user, I want changing my password to revoke all my other sessions, so that a leaked password locks out other devices.

### Cross-cutting

55. As an API consumer, I want every error as an RFC 9457 problem detail (`type`, `title`, `status`, `detail`) with a stable `code`, so that clients can branch on the machine-readable code.
56. As an API consumer, I want a stable, documented set of `code` values, so that I can rely on them.
57. As an operator, I want login/register/refresh rate-limited, so that brute-force is slowed.
58. As an operator, I want the OpenAPI schema generated from the code and diffed against the contract, so that drift is caught in CI.

## Implementation Decisions

### Stack

- FastAPI + Python, async endpoints and async database access.
- SQLAlchemy 2.0 async ORM with Alembic migrations.
- Pydantic v2 schemas for request/response validation and serialization.
- PostgreSQL in production; SQLite for local development and tests.
- Argon2id password hashing, minimum 8 characters, no forced character-class rules.
- UUID v4 string identifiers for users and tasks.

### Contract & conventions

- The OpenAPI spec is the single source of truth; the app's generated schema must match `docs/openapi.yaml`.
- Base path `/api/v1`.
- Pagination is `_start`/`_end` with an `x-total-count` response header; the same convention applies to both `GET /tasks` and `GET /users`.
- Sorting: `_sort` + `_order` (`asc` default). Enum fields sort in their declared spec order — `status`: `todo, in-progress, done, blocked`; `priority`: `low, medium, high`.
- PATCH semantics: omitted field = unchanged; explicit `null` = clear.
- Error envelope is RFC 9457: `type`, `title`, `status`, `detail`, plus a stable `code`. Fixed `code` set: `validation_error`, `unauthorized`, `forbidden`, `not_found`, `conflict`, `too_many_requests`, `internal_error`.

### Domain model

- **Single tenant**: one shared workspace, no organization/team boundary.
- **Two fixed roles**: `admin` and `member`, with rules hardcoded per role — no permission/ACL system.
- **User**: identified by a unique, case-insensitive email (lowercased). Lifecycle is register → role change → hard delete; no status/soft-disable.
- **Task**: has `title` (required), optional `description`/`priority`/`dueDate`/`assigneeId`, a `status`, and `createdAt`/`updatedAt`. `assigneeId` may be `null` (unassigned).
- **Ownership = assignment**: a member may update or delete only tasks assigned to them, and may change the assignee only on a task they already own (no self-assignment of others' tasks). Admins may act on any task.
- **Status machine** (from decisions, not a code prototype):

```
todo → in-progress → done
blocked: entered from todo or in-progress; clearing returns to the prior state
never born done (reject status=done on create)
```

### Authorization rules

- Self-registration always produces a `member`; the first admin is seeded via an env var (e.g. `ADMIN_EMAIL`), not by "first user is admin".
- `PATCH /users/{id}/role` and `DELETE /users/{id}` are admin-only.
- Demoting or deleting the last admin is blocked; an admin cannot delete their own account.
- `GET /users` and `GET /users/me` are available to any authenticated user.
- Task mutation (update/delete) is allowed for the assignee, or any admin; otherwise 403.
- Deleting a user sets their tasks' `assigneeId` to `null`.

### Auth & session model

- Access token: JWT bearer, 15-minute lifetime, carries the session identifier.
- Refresh token: stateful, stored server-side in a session record; 30-day lifetime, sliding on rotation; rotated on every refresh (single-use — presenting a stale token revokes the whole session).
- `POST /auth/refresh` returns both a new `accessToken` and a new `refreshToken`.
- `POST /auth/logout` revokes the session identified by the access token's session identifier.
- Password change revokes every other session but keeps the current one.
- Email normalization: lowercase + trim before uniqueness check; duplicate → 409.

## Testing Decisions

- **What makes a good test**: assert only on external behavior — HTTP status, response headers (e.g. `x-total-count`), and JSON body shape/values. Never assert on implementation details (queries, internal call order, table names).
- **The single seam**: the HTTP boundary. Drive the ASGI app through `httpx`/Starlette's `TestClient`, backed by a real per-test SQLite database (not mocks), so persistence and auth paths run for real.
- **Modules exercised (through the seam only)**: auth (register/login/refresh/logout), users (list/me/role/delete), tasks (list/get/create/update/delete/bulk), password.
- **Prior art**: none yet (greenfield) — this spec establishes the pattern; later specs should follow it.
- **Coverage emphasis**: authorization boundaries (member vs admin, own-vs-other task), the status machine (including `done`-on-create rejection and unblock return-to-prior), refresh rotation + reuse detection, last-admin guard, and the RFC 9457 error shape + stable `code` set.

## Out of Scope

The following are deferred (tracked as separate GitHub issues, not part of this spec):

- Settings module (user preferences, theme, language).
- Password reset / forgot-password.
- Profile management beyond `GET /users/me` (e.g. updating one's own name/email).
- Account status / soft-disable ("suspended").
- Search suggestions/autocomplete beyond the `q` substring filter.
- Third-party integrations (payment, shipping, marketing).
- Bulk delete for tasks.
- General rate limiting beyond the auth endpoints.

## Further Notes

- The contract already lives in `docs/openapi.yaml`; the implementation's generated OpenAPI should be diffed against it in CI to catch drift (the "OpenAPI schema diff" requirement).
- The domain vocabulary is defined in `GLOSSARY.md`; use those terms (e.g. "assignee", not "owner"/"handler") in code, tests, and issue titles.
- Three ADRs apply: single-tenant workspace, stateful refresh-token sessions, and fixed two-role authorization — the implementation must not quietly deviate from them.
