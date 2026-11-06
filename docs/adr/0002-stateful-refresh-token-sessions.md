# Stateful refresh-token sessions

Authentication uses stateful refresh tokens: each login/refresh stores a server-side session holding the refresh token, refresh rotates the token (single-use, and presenting a stale one revokes the whole session), and logout revokes the session identified by a session id carried in the access token. We chose stateful sessions over the more common stateless-JWT refresh pattern because stateful sessions make logout and reuse-detection real — a stateless refresh token cannot be reliably revoked, which the requirement's "logout invalidates the session" implies.
