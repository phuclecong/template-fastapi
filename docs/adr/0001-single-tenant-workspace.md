# Single-tenant workspace

This API serves a single shared workspace: one user pool and one task board, with no organization or tenant boundary. We chose single tenancy because this is an authenticated dashboard template, not a SaaS product — threading a tenant id through every query and authorization check would add cost with no current user. Multi-tenancy, if ever needed, is a later, deliberate migration.
