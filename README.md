# Local Chat

A ChatGPT-style chat app that runs entirely on your machine. Replies come from
[Ollama](https://ollama.com), and every conversation is stored in Postgres.

- Streaming replies, with the model's reasoning shown in a collapsible "Thought process"
- Markdown with syntax-highlighted code blocks and copy buttons
- Stop a reply mid-stream (the partial answer is kept), regenerate, or edit an earlier message
- Pick any installed Ollama model per chat; the choice is remembered
- Conversations are titled automatically and grouped by date in the sidebar

```
Browser ── React + Vite (TypeScript)
   │  fetch, NDJSON stream
   ▼
FastAPI (Python) ──► Ollama  (native on the host, uses the GPU)
   │
   ▼
Postgres 16  (Docker, data in the `pgdata` volume)
```

## Prerequisites

| Tool | Used for | Install |
| --- | --- | --- |
| Docker engine | Postgres | Docker Desktop, or `brew install colima docker docker-compose && colima start` |
| [uv](https://docs.astral.sh/uv/) | Python deps | `pipx install uv` |
| Node 20+ | Frontend | `brew install node` |
| Ollama | The model | <https://ollama.com>, then `ollama pull qwen3:0.6b` (or any chat model) |

With Colima, Docker Compose is a CLI plugin. If `docker compose version` fails, link it once:
`mkdir -p ~/.docker/cli-plugins && ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" ~/.docker/cli-plugins/`

## Quick start

```bash
make setup      # creates .env, installs Python + npm dependencies
make db-up      # starts Postgres in Docker and waits until it is healthy
make migrate    # creates the tables
make dev        # backend on :8000, frontend on http://localhost:5173
```

Make sure Ollama is running (`ollama serve`, or open the Ollama app) and has at least one chat
model installed.

### Production-style run

```bash
make start      # builds the UI, then serves UI + API from one server at http://127.0.0.1:8000
```

The server binds to `127.0.0.1`, so it is reachable only from this machine.

## Everyday commands

Run `make` to list them all.

| Command | What it does |
| --- | --- |
| `make dev` | Backend and frontend with hot reload |
| `make start` | Built UI + API on :8000 |
| `make test` | Backend tests (pytest, real Postgres) and frontend tests (Vitest) |
| `make lint` | ruff, mypy, ESLint, Prettier and `tsc` |
| `make format` | Auto-format everything |
| `make hooks` | Install the git pre-commit hooks (same checks as `make lint`) |
| `make migration m="add x"` | Generate a migration after changing `backend/app/models.py` |
| `make db-shell` | psql inside the container |
| `make db-down` | Stop Postgres (data is kept) |
| `make db-reset` | **Delete all chat history** and recreate the database |

## Configuration

Settings are read from `.env` (copied from `.env.example`) and validated at startup.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://chat:chat@localhost:5432/chat` | Must use the `asyncpg` driver |
| `TEST_DATABASE_URL` | `…/chat_test` | Wiped on every test run |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `DEFAULT_MODEL` | empty | Used when a chat has no model; empty means the first installed chat model |
| `SYSTEM_PROMPT` | empty | Sent at the start of every conversation |
| `OLLAMA_TIMEOUT` | `300` | Seconds allowed between tokens (large models load slowly) |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | JSON logs, one object per line, with a request id |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | `chat` / `chat` / `chat` / `5432` | Used by Docker Compose; keep `DATABASE_URL` in step |

Postgres is published on `127.0.0.1` only. Change the default password if other people use this
machine.

## API

| Method | Path | |
| --- | --- | --- |
| GET | `/health` | Liveness |
| GET | `/ready` | Postgres + Ollama reachable (503 otherwise) |
| GET | `/api/models` | Installed chat models and the default |
| GET / POST | `/api/conversations` | List (most recent first) / create |
| GET / PATCH / DELETE | `/api/conversations/{id}` | Read with messages / rename or change model / delete |
| POST | `/api/conversations/{id}/messages` | Send a message, stream the reply |
| POST | `/api/conversations/{id}/regenerate` | Replace the last reply |
| PUT | `/api/conversations/{id}/messages/{message_id}` | Edit a user message, drop later turns, stream a new reply |

The three streaming endpoints return `application/x-ndjson`, one JSON event per line:
`user_message`, `thinking`, `delta`, `error`, `title`, `done`. Closing the connection stops the
model; the text received so far is saved with status `stopped`.

Interactive docs: <http://localhost:8000/docs>.

## Project layout

```
backend/
  app/
    main.py            app factory, request logging, health/static mounting
    config.py          pydantic-settings
    models.py          Conversation, Message (SQLAlchemy 2.0)
    chat_service.py    model choice, history, streaming + persistence, titles
    ollama.py          async Ollama client
    routers/           health, models, conversations
  alembic/             migrations
  tests/               pytest against the chat_test database, with a fake LLM
frontend/
  src/
    useChat.ts         state, streaming, stop/regenerate/edit, URL routing (#/c/<id>)
    api.ts             REST calls + NDJSON parser
    components/        Sidebar, MessageList, MessageItem, Markdown, Composer, ModelPicker
docker-compose.yml     Postgres 16 (+ creates chat_test on first start)
```

## Troubleshooting

- **"Can't reach Ollama"**: start it with `ollama serve` or the Ollama app; `curl localhost:11434/api/version` should answer.
- **No models in the picker**: `ollama pull qwen3:0.6b` (small) or any chat model, then press ↻ next to the picker. Embedding-only models are hidden.
- **Port 5432 already in use**: set `POSTGRES_PORT=5433` in `.env` and update both database URLs to match.
- **Tests exit with "Test database unreachable"**: run `make db-up`. If the `pgdata` volume existed before `chat_test` was added, create it with `make db-shell` then `CREATE DATABASE chat_test;`.
