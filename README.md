# pusher-go-advanced

An RSS + market-data **AI daily-report pusher**. A multi-agent pipeline reads each
user's portfolio and curated RSS feeds, pulls quotes from free market-data libraries,
generates a daily analysis report with an LLM, persists it, and emails it out. A
cross-platform Rust CLI drives the whole thing.

The backend is a **Python / FastAPI** app packaged as a **Tencent SCF web function**
(uvicorn behind API Gateway), with a **Timer trigger** for the scheduled 08:00 run.

## Architecture

```
┌──────────┐   HTTPS    ┌─────────────────────────────┐
│ Rust CLI │ ─────────► │  FastAPI (SCF web function) │
│ (pusher) │            │  auth · portfolio · report  │
└──────────┘            │  trigger/job · timer        │
                        └──────────────┬──────────────┘
                                       │
                  ┌────────────────────┼─────────────────────┐
                  ▼                    ▼                      ▼
            MySQL (PyMySQL)   Market data providers      DeepSeek LLM
            users/portfolios  akshare → efinance (cn)    Planner → market/
            reports/jobs/...   yfinance (hk/us)          news/sector agents →
                              RSS via feedparser         per-user advisor →
                                                         Reviewer
```

Triggering a report is **asynchronous**: `trigger-report` returns a `job_id`
immediately (HTTP 202), the pipeline runs in the background as a job state machine,
and the CLI polls the job until it finishes (avoiding the API Gateway timeout).

## Repository layout

| Path | What it is |
|------|------------|
| `server/`  | FastAPI backend, agent pipeline, data layer, DB models, tests |
| `cli/`     | Rust CLI (`pusher`) — clap commands, config + token persistence |
| `sql/`     | `schema.sql` — MySQL schema (users, portfolios, fund_holdings, reports, rss_sources, jobs) |
| `deploy/`  | `serverless.yml`, `build_layer.sh`, bootstrap, deploy notes |
| `docs/`    | Design spec and implementation sub-plans |

## Backend

### Requirements

- Python 3.10+
- MySQL 8.0
- A DeepSeek API key (for the LLM pipeline)

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
| `DEEPSEEK_API_KEY` | – | LLM key (server-wide; users may also supply their own) |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Analyst/advisor model |
| `PLANNER_MODEL` | `deepseek-r1` | Planner model |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` | – / `587` | SMTP relay for report emails |
| `EMAIL_FROM` / `EMAIL_PASSWORD` | – | Sender address and credential |
| `TIMER_SECRET` | – | Shared secret authenticating the SCF timer call |

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

Point the CLI at a non-default backend with the global `--endpoint <url>` flag.

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

Packaged as a Tencent SCF **web function** (uvicorn via `server/scf_bootstrap`) with
dependencies shipped as a layer. See [`deploy/README.md`](deploy/README.md) and
[`deploy/serverless.yml`](deploy/serverless.yml). The Timer trigger runs the pipeline
daily at 08:00 (Beijing).

> Note: `akshare` / `efinance` / `yfinance` rely on unofficial upstream endpoints —
> run one real smoke call per library before a first production deploy.

## Design docs

- Spec: [`docs/superpowers/specs/2026-06-25-pusher-go-advanced-design.md`](docs/superpowers/specs/2026-06-25-pusher-go-advanced-design.md)
- Implementation sub-plans: [`docs/superpowers/plans/`](docs/superpowers/plans/)
