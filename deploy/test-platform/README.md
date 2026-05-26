# AiChatTrpg Public Test Platform Deployment

This directory contains the Docker Compose shape used for the hosted
registration-gated test deployment at `test.aichattrpg.com`.

## Shape

- `edge`: host-port `80` nginx router. It keeps the static showcase on
  `aichattrpg.com` and proxies `test.aichattrpg.com` to the test app.
- `frontend`: built Vite app served by nginx.
- `backend`: FastAPI app on the internal Compose network.
- `db`: isolated Postgres database volume for public test accounts/content.

Do not bind this stack to host port `443` on the Tokyo VPS. That port is owned
by VPN services. Cloudflare currently provides public HTTPS at the edge.

## Server Layout

The Tokyo VPS deploy uses this layout:

```text
/opt/chatrpg-test/
  .env
  docker-compose.yml
  edge.nginx.conf
  app/
  secrets/
    auth.json
    backend.env
    README.md
```

Secrets stay server-local and are not committed.

## Required Files

- `.env`: Compose interpolation values such as `POSTGRES_PASSWORD`.
- `secrets/backend.env`: backend runtime environment such as `JWT_SECRET`,
  invite codes, registration flags, and optional provider keys.
- `secrets/auth.json`: bootstrap admin user list for the backend.

Use the example files in this directory as a template only. Generate fresh
server values for every deployment.

## Validation

From the server:

```bash
docker compose -f /opt/chatrpg-test/docker-compose.yml ps
curl -fsS -H 'Host: aichattrpg.com' http://127.0.0.1/ >/dev/null
curl -fsS -H 'Host: test.aichattrpg.com' http://127.0.0.1/api/health
curl -fsS -H 'Host: test.aichattrpg.com' http://127.0.0.1/api/auth/registration-status
```

From outside Cloudflare:

```bash
curl -fsSI https://aichattrpg.com/
curl -fsSI https://test.aichattrpg.com/
curl -fsS https://test.aichattrpg.com/api/auth/registration-status
```
