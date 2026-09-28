# AEGIS Investigation Console (`apps/frontend`)

React frontend for the AEGIS attribution platform — the production foundation for
**Phase 23 · Investigation UI** of `AEGIS_Step_by_Step_Implementation_Plan.md`.

- **Stack**: Vite 5 · React 18 · TypeScript (strict) · React Router 6 · ESLint 9 (flat config)
- **Styling**: hand-rolled design system in `src/styles/*.css` (CSS variables, dark
  investigation-tool theme, dense tables, badges, panels) — no UI framework
- **Charts**: inline SVG (timeline bars, sparklines, score bars, circle-layout graph) — no chart library
- **API**: typed fetch client (`src/api/client.ts`) mirroring the canonical Pydantic schemas

## Scripts

| Script          | What it does                                              |
| --------------- | --------------------------------------------------------- |
| `npm run dev`   | Vite dev server on `:5173`, proxies `/api` + `/health` to `http://127.0.0.1:8000` |
| `npm run lint`  | ESLint over `src/**` and `vite.config.ts`                  |
| `npm run typecheck` | `tsc --noEmit` for `tsconfig.json` + `tsconfig.node.json` |
| `npm run build` | typecheck + `vite build` → `dist/`                         |
| `npm run preview` | Serve the production build                               |

CI (`.github/workflows/ci.yml`, `frontend` job) runs `npm ci`, `lint`, `typecheck`,
`build` in this directory on Node 20 — `package-lock.json` is committed for `npm ci`.

## Environment

| Variable          | Default          | Purpose                                   |
| ----------------- | ---------------- | ----------------------------------------- |
| `VITE_API_BASE`   | `/api`           | Base for `/api/v1/*` routes               |
| `VITE_HEALTH_URL` | `/health`        | Health probe base (`/health`, `/health/db`) |
| `VITE_PROXY_TARGET` (dev only) | `http://127.0.0.1:8000` | Backend origin for the dev proxy |

## Backend endpoints wired

All calls correspond to routes that exist in `src/aegis/api/app.py` — nothing else is called.

| Endpoint                                   | Method | Used by |
| ------------------------------------------ | ------ | ------- |
| `/health`                                  | GET    | header health indicator (polled every 15 s) |
| `/health/db`                               | GET    | header health indicator |
| `/api/v1/sources`                          | POST   | Source reliability screen |
| `/api/v1/evidence`                         | POST   | Evidence explorer (ingest form) |
| `/api/v1/evidence/{id}`                    | GET    | Evidence explorer (lookup + drawer) |
| `/api/v1/evidence/{id}/provenance`         | GET    | Evidence drawer (parents + derivations) |
| `/api/v1/analysis/synthetic`               | POST   | Hypotheses, attribution, graph, actor scores |

## Screens and their data status

| # | Route              | Screen                | Data |
| - | ------------------ | --------------------- | ---- |
| 1 | `/`                | Case list + new case  | Live durable case API |
| 2 | `/cases/:id`       | Case workspace        | Live case metadata + durable workspace counts |
| 3 | `/evidence`        | Evidence explorer     | **Live** — fetch by ID, ingest, provenance drawer |
| 4 | `/actors/:id`      | Actor profile (13 sections) | Planned-endpoint states + live session scores/explanations |
| 5 | `/timeline`        | Timeline              | Derived from session evidence (no timeline endpoint yet) |
| 6 | `/graph`           | Graph                 | Derived from session hypotheses (no graph endpoint yet) |
| 7 | `/attribution`     | Attribution assessment| **Live scores** from a session run; assessment fields marked unavailable |
| 8 | `/hypotheses`      | Hypothesis comparison | **Live** — runs `POST /api/v1/analysis/synthetic` |
| 9 | `/sources`         | Source reliability    | **Live** registration; table is session-scoped (no list endpoint) |
| 10| `/reports`         | Report builder        | Client-side preview + live case-scoped JSON/CSV/STIX/PDF export |

Screens never invent data: where an endpoint is missing, the panel states the gap and the
planned route.

## Layout

```
src/
├── main.tsx            # entry: router + session provider + stylesheets
├── App.tsx             # route table (plan §23, screens 1–10)
├── api/                # client.ts (typed fetch), types.ts (schema mirrors), parse.ts
├── hooks/useApi.ts     # GET hook with loading/error/reload + abort
├── store/session.tsx   # session-only store (no list endpoints to re-read from)
├── components/         # AppShell, Panel, DataTable, Drawer, States, SVG charts…
├── pages/              # one file per screen
├── lib/format.ts       # date/id/percentage helpers
└── styles/             # tokens · base · layout · components
```
