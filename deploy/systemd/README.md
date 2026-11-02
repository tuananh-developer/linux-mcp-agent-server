# Native systemd deployment — implementation brief

> The runnable unit and production environment template are intentionally absent on `team-handoff`. Member 2 must implement and validate them on Ubuntu 24.04.

## Required deliverables

- `linux-mcp-agent.service` and non-secret `server.env.example`.
- Dedicated non-root `linux-mcp-agent` user/group.
- Loopback-only application bind and restrictive file ownership/modes.
- Restart/stop behavior and systemd hardening appropriate to the application.
- Explicit journal access design and explanation of any broader `systemd-journal` group privilege.
- Install, upgrade and rollback procedure.

Never commit real secrets or production environment files.

## Acceptance

- Service starts, restarts and stops on Ubuntu 24.04.
- Effective identity is dedicated and non-root.
- MCP and Keycloak listeners are loopback-only.
- The service is unable to write protected host paths.
- Member 3 records service identity, sandbox settings, listening sockets and journal-access tests.
