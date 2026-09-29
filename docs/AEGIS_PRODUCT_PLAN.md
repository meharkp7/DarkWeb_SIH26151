# AEGIS — Product architecture & delivery order

Locked reference for navigation, screen purpose, and implementation priority. Do not add global nav items for Evidence, Network, Timeline, Attribution, or Financials — those live inside the investigation workspace.

## Navigation

- Command Center
- Investigations (All / Priority Queue / Assigned to Me)
- Threat Watch
- Reports
- Administration (Team, Audit, System)

## Investigation workspace tabs

Overview | Evidence | Network | Timeline | Assessment

## Delivery order

| Priority | Work |
| -------- | ---- |
| P0 | Authentication — token persistence, API client credentials, WebSocket, session expiry UX |
| P1 | Demo seeding — FK order, coherent heavy dataset |
| P2 | Command Center — posture, priority queue, analytical charts from real data |
| P3 | Investigation workspace — full tab integration |
| P4 | Visualization depth |
| P5 | Threat Watch — events + live stream |
| P6 | Reports from case state |
| P7 | Context-aware AEGIS Agent |
| P8 | Admin / audit |
| P9 | Polish — a11y, loading/error states, performance |

## Dataset target (demo)

5–10 cases, 50+ actors, 500+ entities, 3k–5k evidence, 2k+ relationships, coherent case → actor → evidence → hypothesis graph.

## API surface (integration)

`/dashboard/summary`, `/dashboard/cases`, `/cases/{id}/*` (evidence, entities, relationships, timeline, hypotheses, assessment, signals, metrics), `/threat-watch/events`, live WebSocket on audit/event stream.
