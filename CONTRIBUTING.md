# Contributing

Thank you for your interest in brandcal. The project is in early development, so please
open an issue to discuss a change before starting on it.

1. Branch from `work` and open your pull request against `work` (never `main`).
2. Keep changes small and focused, with tests.
3. Run the checks before committing:
   `ruff check .`, `ruff format --check .`, `mypy src`, `pytest`,
   `python scripts/privacy_scan.py`.
4. Reference issues with `Refs #N`; maintainers close issues.
5. Never commit real personal data. Use obviously fake examples (`Example Co`,
   `example.com`).

AI agents must also follow [AGENTS.md](AGENTS.md).

By contributing you agree that your contributions are licensed under the MIT licence.
