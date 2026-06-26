# pusher-go-advanced

An RSS + market-data **AI daily-report pusher**. A multi-agent pipeline reads each
user's portfolio and curated RSS feeds, pulls quotes from free market-data libraries,
generates a daily analysis report with an LLM, persists it, and emails it out. A
cross-platform Rust CLI drives the backend HTTP API.

The backend is a **Python / FastAPI** app. In production the scheduled daily run is
deployed to **Tencent SCF** as an **Event function + Timer trigger** (08:00 Beijing).
See [Deployment](#deployment) for why the HTTP API is not currently cloud-hosted.

## Architecture

```
┌──────────┐   HTTPS    ┌─────────────────────────────┐
│ Rust CLI │ ─────────► │  FastAPI backend            │
│ (pusher) │            │  auth · portfolio · report  │
└──────────┘            │  trigger/job · timer        │
                        └──────────────┬──────────────┘
                                       │
                  ┌────────────────────┼─────────────────────┐
                  ▼                    ▼                      ▼
            MySQL (PyMySQL)   Market data providers      LLM pipeline
            users/portfolios  akshare → efinance (cn)    Planner → market/
            reports/jobs/...   yfinance (hk/us)          news/sector agents →
                              RSS via feedparser         per-user advisor →
                                                         Reviewer
```

**Multi-agent pipeline.** A Planner drafts the run; market / news / sector analyst
agents gather and summarize data; a per-user advisor tailors it to each portfolio; a
Reviewer assembles the final HTML report. Each external data source is isolated so a
single upstream failure degrades gracefully instead of killing the job.

**Dual LLM providers.** Calls are routed by model-name prefix: `kimi-*` / `moonshot-*`
go to **Moonshot (Kimi)**, everything else to **DeepSeek**. Roles map to models via
`PLANNER_MODEL` / `ANALYST_MODEL` / `REVIEWER_MODEL`, so you can mix providers per role.

**Asynchronous triggering.** `trigger-report` returns a `job_id` immediately (HTTP 202),
the pipeline runs in the background as a job state machine, and the CLI polls the job
until it finishes.

## Repository layout

| Path | What it is |
|------|------------|
| `server/`  | FastAPI backend, agent pipeline, data layer, DB models, SCF handlers, tests |
| `cli/`     | Rust CLI (`pusher`) — clap commands, config + token persistence |
| `sql/`     | `schema.sql` — MySQL schema (users, portfolios, fund_holdings, reports, rss_sources, jobs) |
| `deploy/`  | One-click SCF deploy (`deploy.sh`, `deploy_scf.py`, `publish_layer.py`) + notes |
| `docs/`    | Design spec and implementation sub-plans |

## Backend

### Requirements

- Python 3.10+
- MySQL 8.0
- A DeepSeek API key, and optionally a Kimi (Moonshot) key, for the LLM pipeline

### Setup

```bash
cd server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Initialize the schema
mysql -u <user> -p <database> < ../sql/schema.sql
```

### Configuration (environment variables)

Required:

| Variable | Description |
|----------|-------------|
| `MYSQL_HOST` / `MYSQL_PORT` | MySQL host / port (port defaults to `3306`) |
| `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL credentials and database |

Optional:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | – | DeepSeek key (server-wide; users may also supply their own) |
| `KIMI_API_KEY` | – | Moonshot (Kimi) key, used when a role's model is `kimi-*` |
| `KIMI_ENDPOINT` | `https://api.moonshot.cn/v1` | Moonshot base URL (intl: `https://api.moonshot.ai/v1`) |
| `PLANNER_MODEL` | `deepseek-r1` | Planner model |
| `ANALYST_MODEL` | `DEEPSEEK_MODEL` | Market / news / sector / advisor model |
| `REVIEWER_MODEL` | `ANALYST_MODEL` | Final-review (HTML assembly) model |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Fallback model for analyst/reviewer when unset |
| `LLM_TIMEOUT` | `300` | Per-call LLM timeout (seconds) |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` | – / `587` | SMTP relay for report emails |
| `EMAIL_FROM` / `EMAIL_PASSWORD` | – | Sender address and credential |
| `TIMER_SECRET` | – | Shared secret authenticating the SCF timer call |

Model names must match each provider's actual model IDs (e.g. query Moonshot's
`GET /v1/models`).

### Run locally

```bash
cd server
uvicorn app.main:app --reload --port 9000
```

Health check: `GET /health` → `{"status": "ok"}`.

### Tests

```bash
cd server
pytest          # requires a reachable MySQL; network/LLM/SMTP are mocked
```

## CLI (`pusher`)

```bash
cd cli
cargo build --release      # binary at target/release/pusher
```

Configuration and the auth token are stored in `~/.pusher/config.toml`.

```bash
# Account
pusher register --email you@example.com
pusher login    --email you@example.com
pusher logout

# Portfolio (quantity/cost optional; holdings % is derived, never entered)
pusher portfolio add-stock 600519 --market cn --quantity 100 --cost 1600
pusher portfolio add-stock AAPL   --market us
pusher portfolio add-fund  012345
pusher portfolio list
pusher portfolio remove <id>

# Reports
pusher trigger run         # fires the pipeline, shows a live spinner while polling
pusher report today
pusher report get 2026-06-25
pusher report list
```

Point the CLI at a backend with the global `--endpoint <url>` flag.

## HTTP API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET`  | `/health` | – | Liveness |
| `POST` | `/register` | – | Create account |
| `POST` | `/login` | – | Obtain bearer token |
| `POST` | `/portfolio` | bearer | Add a holding |
| `GET`  | `/portfolio` | bearer | List holdings |
| `DELETE` | `/portfolio/{id}` | bearer | Remove a holding |
| `POST` | `/trigger-report` | bearer | Start a report job → `202 {job_id}` |
| `GET`  | `/job/{job_id}` | bearer | Poll job status (owner-scoped) |
| `GET`  | `/report/today` | bearer | Today's report |
| `GET`  | `/report/{date}` | bearer | Report for a date |
| `GET`  | `/report/list` | bearer | List reports |
| `POST` | `/internal/timer`, `/` | timer secret | Scheduled run entrypoints |

Auth uses a random 128-char DB-backed bearer token (forgery-resistant, easy to revoke).

## Deployment

A one-click script deploys the scheduled daily run to Tencent SCF:

```bash
source deploy/.env        # MYSQL_* / TENCENT_* / DEEPSEEK_* / KIMI_* / EMAIL_* / TIMER_SECRET
bash deploy/deploy.sh
```

`deploy.sh` builds the dependencies as a **linux/amd64 Layer**, publishes it to COS, then
creates/updates an **Event function** (`pusher-pipeline`) and attaches a **daily 08:00
Timer**. Full details and gotchas are in [`deploy/README.md`](deploy/README.md).

> **Why only the daily run, not the HTTP API?** API Gateway has been discontinued
> ("停止售卖") on the target account, and SCF HTTP/Web functions accept only `apigw`
> triggers (no timer). So the cloud deployment runs the pipeline as a timer-driven
> Event function; the FastAPI HTTP API still runs locally and is fully tested, but is
> not currently cloud-hosted. Users / portfolios are managed directly via SQL.

> Note: `akshare` / `efinance` / `yfinance` rely on unofficial upstream endpoints —
> run one real smoke call per library before a first production deploy.

## Design docs

- Spec: [`docs/superpowers/specs/2026-06-25-pusher-go-advanced-design.md`](docs/superpowers/specs/2026-06-25-pusher-go-advanced-design.md)
- Implementation sub-plans: [`docs/superpowers/plans/`](docs/superpowers/plans/)
