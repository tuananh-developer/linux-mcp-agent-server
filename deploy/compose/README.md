# Infrastructure Compose — implementation brief

> The runnable Compose model and environment template are intentionally absent on `team-handoff`. Member 2 implements them; member 3 owns independent smoke tests.

## Target services

- PostgreSQL 18.6: private persistence for Keycloak only; no host-published database port.
- Keycloak 26.8.1: authorization server; bind its HTTP listener to host loopback for reverse-proxy use.
- Caddy 2.11.x: optional LAN profile; publish only the intended HTTPS ingress.

## Required controls

- Use named volumes and an internal database network.
- Add health checks and dependency readiness.
- Apply `no-new-privileges` and least-privilege capabilities.
- Use non-secret `.env.example` values; real random secrets belong only in an ignored local `.env`.
- Never commit generated credentials, tokens, database dumps, Caddy CA private keys or production environment files.
- Validate the rendered Compose model in CI and verify container health on Ubuntu 24.04.

## Acceptance

Member 2 supplies the Compose model, environment template and runbook. Member 3 records configuration validation, container health, socket exposure and cross-device HTTPS smoke tests.
