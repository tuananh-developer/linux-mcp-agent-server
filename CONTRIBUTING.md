# Contributing

1. Use `team-handoff` as the shared integration base for the three student workstreams.
2. Create a feature branch from the latest `team-handoff`; do not push directly to `main` or directly to the shared branch.
3. Open pull requests back into `team-handoff`. The group leader reviews and integrates changes.
4. Keep the server read-only. Never add arbitrary shell execution, caller-controlled paths/units or destructive host operations.
5. Add unit, integration and security tests for every new system boundary and update requirement/test traceability.
6. Run `uv sync --all-groups`, `uv run ruff check .`, `uv run pyright` and `uv run pytest`.
7. Include the test commands and actual results, design decisions, security impact, deployment evidence and known limitations in each PR.
8. Update `uv.lock` after dependency changes and commit it. CI resolves exact direct dependency pins but does not replace a reviewed lockfile.
