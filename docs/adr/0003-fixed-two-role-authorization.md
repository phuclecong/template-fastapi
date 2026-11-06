# Fixed two-role authorization

Authorization is two fixed roles — `admin` and `member` — with rules hardcoded per role: admins manage users and all tasks; members manage only tasks assigned to them. We deliberately did not build a permission or ACL system. The requirement's "roles and permissions" and "per-resource authorization" are satisfied by per-role rules today, and a grant system would be speculative complexity for a template.
