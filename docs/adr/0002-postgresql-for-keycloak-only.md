# ADR-0002: Use PostgreSQL only for Keycloak persistence

- **Status:** Accepted.
- **Decision date:** 2026-11-17.

## Context

The MCP service collects Linux host metrics on demand. It does not maintain application users, history, dashboards, metric retention or business records. Keycloak requires persistent storage for realm, client and identity configuration.

## Decision

Use PostgreSQL 18.6 as Keycloak's persistence database only. Do not add an application database for metrics or process snapshots. Run PostgreSQL on the Compose private network without a published host port.

For the PostgreSQL 18 official image, mount the named data volume at `/var/lib/postgresql`, which contains the image's version-specific data directory.

## Consequences

- The MCP application remains stateless with respect to telemetry and does not need an ORM or application schema.
- PostgreSQL remains necessary for the selected Keycloak deployment, but not for the MCP Core itself.
- Keycloak backups and PostgreSQL volume persistence are identity-infrastructure responsibilities.
- Existing PostgreSQL data must be backed up and migrated before changing a previously used volume mount. Never delete a volume as a shortcut.
