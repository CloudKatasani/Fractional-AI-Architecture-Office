# Before you host the Architecture Office anywhere

The prototype was built local-first: one laptop, one presenter, synthetic data. Most of it carries
over to a server unchanged — but a few things that are fine on a laptop matter once other people can
reach it. Read this before following the [AWS guide](AWS.md).

**Good news first:** the single-server path needs **no code changes**. The FastAPI process already
serves the built UI, there is already a health endpoint, and the data generator is already the
install step. Everything in §1 is handled by *where* you put the app (behind Caddy's password, bound to
`127.0.0.1`), not by editing it. The `B*` and `C*` identifiers are referenced from the AWS guide.

---

## 1. Blocking for anything other people can reach

| # | Problem | Where | What has to happen |
|---|---------|-------|--------------------|
| **B1** | **There is no authentication.** The UI's user switcher is a dropdown saved in the browser's `localStorage`. The approval API takes the deciding user as a field in the request body and checks only that *that user's* role may approve — not that the caller *is* that user. Anyone who reaches the site can approve or reject any proposal as the principal architect, and the audit trail records the name they claimed. | `frontend/src/state/AppState.tsx:73-89`, `backend/app/routers/agents.py:198`, `backend/app/orchestrator/approval_gate.py:81` | Put the whole site behind a gate that only trusted people pass: the Caddy `basic_auth` password in the AWS guide, and optionally a security-group allowlist of office IPs. Treat the audit trail on a hosted demo as "what the demo did", not as evidence of who did it. Real per-user sign-in is out of scope for the prototype (see the README). |
| **B2** | **Anyone can reset a tenant or switch the LLM mode.** `POST /api/v1/admin/reset` regenerates a tenant (discarding every approval and audit event recorded on the server). `PATCH /api/v1/config` switches mock ↔ live for every visitor at once — and live mode spends the server's Anthropic credit. | `backend/app/routers/core.py:131`, `backend/app/routers/core.py:74` | Same gate as B1. Only set `ANTHROPIC_API_KEY` on the server if you are content for any signed-in visitor to turn live mode on. Without the key, live mode is refused with a 400. |
| **B3** | **CORS allows every origin.** Harmless while the API is only reachable through the password-protected proxy (the browser will not send the basic-auth credentials cross-site on its own), but it means the API was never designed to be exposed directly. | `backend/app/main.py:40` | Never open port 8000 in the security group. The AWS guide binds uvicorn to `127.0.0.1` so it cannot be reached except through Caddy. |

## 2. Needs care, not a code change

| # | Issue | Detail |
|---|-------|--------|
| **C1** | **One process, one server.** Each tenant is a SQLite file (`data/<tenant>.db`) opened in WAL mode. The LLM-mode switch and the knowledge-graph cache live in process memory. | `backend/app/db/session.py:35`, `backend/app/llm/client.py:206`. Run **one** uvicorn worker on **one** instance. Several workers would each cache their own graph and LLM mode; several instances would each have their own databases. WAL also rules out network filesystems such as EFS. |
| **C2** | **The data must exist before the app is useful.** Without `data/*.db` every tenant-scoped call returns `503 tenant … has no data yet`. | `backend/app/routers/deps.py:29`. Generation is part of the install (`python -m data_gen.generate --all --if-missing`, ~15 seconds). Regenerating **without** `--if-missing` is destructive: it rebuilds the tenant from the seed. |
| **C3** | **Synthetic dates float with the calendar.** Every date in the data is relative to `DEMO_TODAY`; empty means *today*, so a demo generated on Monday looks subtly different on Friday (renewal windows, end-of-life countdowns). | `backend/app/config.py:48`. Pin `DEMO_TODAY` in `.env` at install time. The AWS guide does this. |
| **C4** | **The UI is picked up at start-up.** The API only serves `frontend/dist` if the folder exists when the process starts. | `backend/app/main.py:69`. Build the UI *before* starting the service, and restart the service after every rebuild. A missing build shows `{"detail":"Not Found"}` at `/`. |
| **C5** | **The data is synthetic and must stay so.** NorthGrid Energy and Meridian Telecom are invented; nothing in the prototype is hardened for real client data (no encryption at rest beyond the EBS volume, no retention controls, no per-user access). | Do not load real client inventories onto a hosted instance. |
| **C6** | **`/docs` loads Swagger UI from a CDN** (`cdn.jsdelivr.net`). | Viewers' browsers need internet access for the API explorer; the app itself does not. |

---

## 3. Environment variables

All read from `/opt/arch-office/.env` (or the process environment, which wins) at start-up.

| Variable | Required | Notes |
|---|---|---|
| `LLM_MODE` | no | `mock` (default, deterministic, offline) or `live`. |
| `ANTHROPIC_API_KEY` | only for live | Keep the file `chmod 600`, owned by the service user (B2). |
| `ANTHROPIC_MODEL` | no | Model for live narratives; the default is set in `.env.example`. |
| `SEED` | no | `42`. Same seed → same data → same agent outputs. |
| `DEMO_TODAY` | recommended | `YYYY-MM-DD`; pin it (C3). |
| `DATA_DIR` | no | `data`, relative to the repository root. |

---

## 4. What is true regardless of how you host it

- **Serve it over HTTPS.** Basic-auth credentials travel with every request; over plain HTTP they
  are readable by anyone on the path. Caddy issues the certificate automatically.
- **The SQLite files are the system of record** for everything the demo changes: approvals,
  decisions, the audit trail, agent runs and autonomy settings. Back those up; everything else can be
  rebuilt from the repository and the seed.
- **Mock mode is a complete demo.** With no API key the server makes no outbound call to a model
  provider at all.
