# AEGIS — deployment

Three free-tier services. Nothing here needs a code change; the console already
reads `VITE_API_BASE` and derives the websocket URL from it.

```
┌──────────────┐   HTTPS + WSS    ┌───────────────┐   postgresql
│    Vercel    │ ───────────────► │    Render     │ ────────────► Supabase
│  static SPA  │                  │  FastAPI + WS │               (Postgres)
└──────────────┘                  └───────────────┘
```

## 1. Database — Supabase

1. **New project** → note the connection string.
2. **Replace the password placeholder** in the URI. Supabase's pooler string
   (`?pgbouncer=true`) will not work: the app uses advisory locks for the
   audit hash chain, and those are session-scoped, so every request must get a
   dedicated backend.
3. Use the **direct** connection, not the transaction pooler.
4. Set `sslmode=require`.

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

## 2. API — Render

```bash
render blueprint launch      # reads render.yaml
```

Or connect the repo and paste `render.yaml` into the blueprint field. The
manifest sets `AEGIS_DATABASE_URL` to **sync: false**, so Render will prompt.

Set in the dashboard:

| Variable | Value |
|---|---|
| `AEGIS_DATABASE_URL` | the Supabase string above |
| `AEGIS_CORS_ORIGINS` | your Vercel origin, **after** step 3 |
| `AEGIS_ENVIRONMENT` | `production` |
| `AEGIS_AUTH_PASSWORD` | set it — the default is a published demo value |

`startCommand` runs `alembic upgrade head` on every boot, so the schema is
migrated on deploy and no manual step is needed.

**The build installs default dependencies only.** `torch`, `xgboost` and
`scikit-learn` are an optional `ml` extra, and Render does not install it. They
were default dependencies until this was changed, which made the image ~2GB —
and on a free-tier host the *build* is what fails: not enough disk, or a build
that outlives the timeout.

They are not needed. Every import of them in the source is deliberately lazy,
inside the function that uses it, and the whole API plus analytics surface
imports with `torch` and `sklearn` absent. Their only consumers are
`POST /api/v1/analysis/synthetic` and the resolution/attribution baselines.
Anything that needs them and cannot find them reports the adapter as
unavailable rather than failing the request.

If you later want the baselines in production, add `--extra ml` to
`buildCommand` and expect a much larger image and a slower cold start.

**Then seed it once**, from your machine against the hosted database:

```bash
uv run python scripts/seed_demo_data.py --reset
```

## 3. Frontend — Vercel

```bash
cd apps/frontend
vercel link
vercel env add VITE_API_BASE production   # https://aegis-api.onrender.com/api
vercel deploy --prod
```

`VITE_API_BASE` is read at **build** time, so it must be set before the build —
adding it afterwards requires a redeploy, not just an env edit.

`vercel.json` also rewrites `/api/*` to the API origin, which is a fallback for
the browser: if `VITE_API_BASE` is unset the SPA still works through the
rewrite. The **websocket** does not go through that rewrite, so
`VITE_API_BASE` is the path that matters for the live console.

Finally, set `AEGIS_CORS_ORIGINS` on Render to the Vercel origin and redeploy
the API.

## Verify

```bash
curl -s https://<api>/health
curl -s -X POST https://<api>/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"analyst@aegis-intelligence.com","password":"<yours>"}'
```

Then open the Vercel URL, sign in, and confirm the sidebar chip reads **Live**
rather than "Reconnecting" — that is the check that the cross-origin websocket
upgrade succeeded end to end.

## Free-tier limits that will show up

- **Render sleeps after ~15 minutes idle.** The console degrades correctly (it
  falls back to REST and says "Reconnecting"), but the first request after a
  sleep takes ~30s. For a walkthrough, keep the service awake or demo locally.
- **Render free gives one web service.** The API and its websocket are the same
  process, which is what this setup assumes.
- **Supabase free pauses after a week of inactivity** and the connection is
  then briefly refused on wake.
- **OpenSearch and Neo4j are not deployed and not needed.** Search falls back to
  Postgres; the graph uses the in-process store. Administration reports both as
  "unavailable", which is advisory rather than an outage.

## Security notes

- `AEGIS_CORS_ORIGINS` must list origins **explicitly**. Credentials with a
  wildcard is the one combination that would make the CORS config unsafe, and
  the middleware rejects it — the allowlist is the property that makes
  credentialed cross-origin safe.
- The app refuses to start against a non-Postgres URL in production, because the
  audit chain depends on Postgres advisory locks.
- Sessions are 15 minutes by default and the sign-in throttle is per-process,
  so it resets on every deploy. Neither is a vulnerability, but both are worth
  knowing before a demo.
