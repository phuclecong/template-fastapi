# Deploying to Vercel

Checklist for deploying this API to Vercel's Python runtime. The app deploys as a
single Vercel Function that serves every route; no start command or Dockerfile is
used. Vercel reads `pyproject.toml` + `uv.lock`, and the root `main.py` exposes the
FastAPI `app` from the `src/` layout.

Read the limitations at the end before treating this as a production setup.

## Prerequisites

- A Vercel account and project.
- A PostgreSQL database (Vercel Marketplace, Neon, or Supabase). SQLite does not
  work on serverless: the filesystem is ephemeral and read-only at runtime.
- `uv` for running migrations locally.

## 1. Provision PostgreSQL

Create the database, then build the async SQLAlchemy URL. Providers hand out a
`postgresql://` URL with `sslmode=require`; change both parts:

```bash
# Provider URL:
#   postgresql://user:pass@host/neondb?sslmode=require
# Vercel environment variable:
DATABASE_URL=postgresql+asyncpg://user:pass@host/neondb?ssl=require
```

- The scheme must be `postgresql+asyncpg` (the app uses the asyncpg driver).
- asyncpg does not accept `sslmode`; use `ssl=require`.
- URL-encode special characters in the password (e.g. `@` → `%40`).
- Prefer the provider's **pooled** hostname (Neon's `-pooler` endpoint, Supabase's
  pooler). Each function instance creates its own engine pool.

## 2. Apply migrations

The app's lifespan seeds System Roles and the first admin on every cold start. If
the tables do not exist, startup fails and every request returns 500, so migrate
**before** the first request reaches the deployment.

```bash
export DATABASE_URL='postgresql+asyncpg://user:pass@host/neondb?ssl=require'
uv run alembic upgrade head
```

Environment variables take precedence over `.env`; the export above overrides the
local SQLite default.

Do not run migrations as a Vercel build command if preview deployments share the
production database — a PR preview would migrate production.

## 3. Configure environment variables

Set these in Vercel (Project → Settings → Environment Variables) or with the CLI.

| Variable                  | Required | Value                                                        |
| ------------------------- | -------- | ------------------------------------------------------------ |
| `DATABASE_URL`            | yes      | `postgresql+asyncpg://...?ssl=require`                       |
| `JWT_SECRET`              | yes      | `openssl rand -hex 32` — otherwise the dev placeholder ships |
| `ENVIRONMENT`             | yes      | `production`                                                 |
| `ADMIN_EMAIL`             | no       | Set **both** admin variables or neither                      |
| `ADMIN_PASSWORD`          | no       | At least 8 characters; seeds the first Administrator         |
| `CORS_ORIGINS`            | yes      | JSON array, e.g. `["https://your-frontend.vercel.app"]`      |
| `PROBLEMS_BASE_URL`       | no       | e.g. `https://your-api.vercel.app/problems`                  |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no   | Defaults to `15`                                             |
| `REFRESH_TOKEN_EXPIRE_DAYS`   | no   | Defaults to `30`                                             |

`ADMIN_EMAIL` without `ADMIN_PASSWORD` (or vice versa) raises at startup.

```bash
npx vercel link
npx vercel env add DATABASE_URL production
npx vercel env add JWT_SECRET production
npx vercel env add ENVIRONMENT production
npx vercel env add ADMIN_EMAIL production
npx vercel env add ADMIN_PASSWORD production
npx vercel env add CORS_ORIGINS production
npx vercel env add PROBLEMS_BASE_URL production
```

Add the same values to Preview/Development if you use those environments.

## 4. Deploy

Use the Vercel CLI:

```bash
npx vercel --prod
```

Or import the GitHub repo in the Vercel dashboard and let each push deploy. Keep
the function region (`iad1` by default) close to the database; on Pro you can
change it in Project Settings.

`vercel.json` sets `maxDuration` to 300 seconds (the Hobby maximum; Pro supports up
to 800) and excludes `tests/` from the function bundle.

## 5. Smoke test

```bash
curl -sS https://<deployment>/api/v1/health
# {"status":"ok"}

curl -sS -X POST https://<deployment>/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@example.com","password":"<ADMIN_PASSWORD>"}'
```

Interactive docs are at `https://<deployment>/docs`. If `/health` works but auth
requests 500, check that migrations ran and that `DATABASE_URL` points at the same
database.

## Limitations

- **SSE (`GET /api/v1/events`) is unreliable on Vercel.** The live event bus is
  in-process, so a mutation handled by one function instance cannot notify a stream
  held by another. Vercel also terminates the invocation at `maxDuration` (300 s on
  Hobby), forcing reconnects. Use polling in production, add a shared broker
  (Redis / Postgres `LISTEN`/`NOTIFY`), or host the API on a long-running service.
- **Auth rate limiting is per-instance** and resets on cold start. Use Vercel WAF
  rate limiting or a shared store for real brute-force protection.
- **Connection pool exhaustion.** Each instance opens its own pool (5 + 10
  overflow). Use a pooled provider endpoint and, if you see
  `prepared statement "__asyncpg_stmt_..." does not exist` or
  `DuplicatePreparedStatementError`, disable prepared statements in
  `src/app/core/database.py`:

  ```python
  engine = create_async_engine(
      get_settings().database_url,
      connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
      poolclass=NullPool,
  )
  ```

- **Seeding runs on every cold start.** `seed_system_roles` and `seed_admin` are
  idempotent, but each instance performs the lookup queries at startup.
- **`ADMIN_PASSWORD` is only used at startup.** Changing it later does not rotate
  the admin password; use `PUT /api/v1/password` instead.
