# Contributing

1. Create a feature branch from `main`.
2. Keep the server read-only. Never add arbitrary shell execution or caller-controlled paths/units.
3. Add unit tests for every new system boundary and update the matching requirement/test traceability.
4. Run `uv sync --all-groups`, `uv run ruff check .`, `uv run pyright`, and `uv run pytest`.
5. Update `uv.lock` after dependency changes and commit it.
6. Submit a pull request with the test output and any security impact.
