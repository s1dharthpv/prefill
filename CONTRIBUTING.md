# Contributing to Prefill

Thanks for helping. Bug reports, questions and pull requests are all welcome.

## Before you start

- Prefill targets Frappe v16. Read the [README](README.md) for how it behaves and
  [NOTES.md](NOTES.md) for how it is built and why.
- For a bug or a request, open an issue first so we can agree on the approach.
- To report a security problem, follow [SECURITY.md](SECURITY.md) instead of opening an issue.

## Set up

```bash
bench get-app https://github.com/s1dharthpv/prefill --branch develop
bench --site <your-site> install-app prefill
cd apps/prefill
pre-commit install
```

## Make a change

1. Branch from `develop`.
2. Keep the change small and focused, and update the README or NOTES.md if behaviour changes.
3. Add or update tests. Server tests run with:
   ```bash
   bench --site <your-site> set-config allow_tests true
   bench --site <your-site> run-tests --app prefill
   ```
4. Run `pre-commit run --all-files` (ruff, eslint, prettier). CI runs the same linters, plus the
   Frappe Semgrep rules and pip-audit, on every pull request.
5. Open a pull request into `develop`. Releases are merged from `develop` into `main`.

## Pull request checklist

- Tests pass and the linters are clean.
- No real customer or financial data in tests, screenshots or issue text.
- Permission rules are still enforced in the controller, not only in the UI.

By contributing you agree that your work is released under the [MIT license](LICENSE).
