# 🐳 Run the Ticket Workflow with Docker

Use Docker when you need parity with production (FastAPI container) or want a self-contained DevUI demo. Keep DevUI local only.

## 📑 Table of contents

- [Key files](#key-files)
- [Prereqs](#prereqs)
- [DevUI workflow (local demo)](#devui-workflow-local-demo)
- [FastAPI workflow (production parity)](#fastapi-workflow-production-parity)
- [Compose cheat sheet](#compose-cheat-sheet)
- [Building images directly](#building-images-directly)
- [Troubleshooting](#troubleshooting)
- [Related docs](#related-docs)

## 📁 Key files

| File | Purpose |
| --- | --- |
| `Dockerfile` | DevUI image (local demos) |
| `Dockerfile.api` | FastAPI image (production parity) |
| `docker-compose.yml` | DevUI stack for daily work |
| `docker-compose.dev.yml` | Hot-reload overlay (bind-mounts source) |
| `docker-compose.api.yml` | API-only stack mirroring Azure runtime |

## ✅ Prereqs

- Docker Desktop ≥ 20.10 with Compose v2
- `.env` populated with Azure OpenAI + Logic App values (see `README.md`)

## 🎨 DevUI workflow (local demo)

```bash
# Rebuild + start
docker-compose up -d --build

# Logs / stop
docker-compose logs -f ticket-devui
docker-compose down
```

Open http://localhost:8080. For hot reload, overlay the dev file:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart ticket-devui  # fast restarts
```

Use this path while editing Python; rebuild only for dependency changes.

## ⚡ FastAPI workflow (production parity)

```bash
docker-compose -f docker-compose.api.yml up -d --build
docker-compose -f docker-compose.api.yml logs -f
docker-compose -f docker-compose.api.yml down
```

- Default host port 8000 (`API_PORT` overrides)
- Dispatcher forced into simulation mode
- Check `http://localhost:8000/docs`

## 📝 Compose cheat sheet

```bash
docker-compose up           # attach logs
docker-compose up -d        # detached
docker-compose build --no-cache
docker-compose ps
docker-compose logs -f ticket-devui
docker-compose exec ticket-devui /bin/bash
DEVUI_PORT=9090 docker-compose up -d
API_PORT=9000 docker-compose -f docker-compose.api.yml up -d
```

## 🔨 Building images directly

```bash
docker build -t ticket-devui:latest .
docker build -f Dockerfile.api -t ticket-api:latest .
docker buildx build --platform linux/amd64,linux/arm64 -f Dockerfile.api -t ticket-api:latest .
```

Push only the API image to registries; DevUI stays local.

## 🔧 Troubleshooting

| Issue | Action |
| --- | --- |
| Container exits | `docker-compose logs <service>` – usually missing `.env` |
| Port clash | `lsof -i :8080` or `:8000`, stop conflicting proc |
| Env vars missing | `docker-compose exec ticket-devui env | grep AZURE` |
| Cache stuck | `docker-compose build --no-cache` |
| Need shell | `docker-compose exec ticket-devui /bin/bash` |

## 📚 Related docs

- `docs/run-local.md` for non-Docker loops
- `docs/testing-ci.md` for pytest + smoke tests
- `docs/cloud-deploy.md` for Azure Container Apps rollout

