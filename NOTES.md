# NOTES

Working notes for the Prefill build. Spec: `~/Frappe/Presets/docs/SPEC.md`.

## Step 0: name

Approved by the owner on 2026-10-29: `prefill` (title "Prefill").
Checked the same day: PyPI (`prefill`, `frappe-prefill`: 404), GitHub repo-name search (no Frappe app), `frappe/marketplace` `apps/` listing (126 entries, no match), general web search (no Frappe app).
Not covered: the Marketplace search box itself (cannot be queried from here). Owner to type `prefill` into it before registering.

## Step 1: scaffold and spike (Frappe 16.54.0, Python 3.14)

Scaffold: `bench new-app prefill`, branch `develop`, GitHub workflow = yes.

Changes made to the generated scaffold (commit 2):
- Added `[tool.bench.frappe-dependencies]` with `frappe = ">=16.0.0,<17.0.0"` (the generated file has none; Marketplace repo validation fails without it).
- `required_apps = []` was commented out; now a real empty list.
- `license.txt` renamed to `LICENSE`.
- `ci.yml` ran `bench init` on Frappe's default branch; now `--frappe-branch version-16`.

Spike results, from the installed v16 source and one runtime call:
- `frm.add_custom_button(label, fn, group)` exists (`form/form.js`) and passes `group` to `page.add_inner_button`. Grouping is confirmed at source level only; the rendered dropdown is checked in the UI smoke test.
- v16 test base classes: `IntegrationTestCase` and `UnitTestCase`, `from frappe.tests import IntegrationTestCase`. Files are `frappe/tests/classes/integration_test_case.py` and `unit_test_case.py`.
- `frappe.model.get_permitted_fields(doctype, parenttype, user, permission_type, *, ignore_virtual)`: `permission_type="write"` is valid. `Meta.get_permlevel_access` reads `perm.get(permission_type)`, so it uses the DocPerm `write` column. Ran for ToDo as Administrator, no error. Closes SPEC open question 4 (no need for `has_permlevel_access_to`).
  - Caveat: the returned list includes system default fields (name, owner, creation, ...) and optional columns. It is a permlevel filter only; the SPEC 3.5 allowlist still has to be applied on top. It does not look at `read_only` or `fetch_from`.
  - Caveat: verified for Administrator only. The restricted-user case is covered by the permission tests in step 2.

Local gates on the empty app:
- `ruff check` and `ruff format --check`: clean (one trailing blank line in `hooks.py` was reformatted).
- Semgrep (`frappe/semgrep-rules` plus `r/python.lang.correctness`): 62 rules, 0 findings.
- `bench run-tests --app prefill`: runner works, 0 tests.
- `app_name` equals package folder, no symlinks, `__init__.py` has no calls.

## Not done yet

- GitHub CI (`ci.yml`, `linter.yml`) has not run: there is no remote. `linter.yml` only triggers on pull requests, so it needs a PR from `develop`. Creating the private remote needs the owner's go-ahead.
- Fresh-site install from README only (done after the README exists).

## Open questions

- SPEC 12 Q2a: is a v16-only app accepted by the Compatibility audit and review.
- SPEC 12 Q3: demand check with 3 to 5 ERPNext users.
- Private repo (assignment) vs public GitHub (Marketplace): needs the owner's go-ahead before any public push.
- `requires-python = ">=3.14"` in the scaffold matches Frappe v16 (`>=3.14,<3.15`); confirm Frappe Cloud v16 images use 3.14.
