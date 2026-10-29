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

## Step 2: DocTypes, hooks, permissions

Built: Form Preset, Form Preset Share, Form Presets Settings, and the child table Form Preset Excluded DocType (SPEC 3.3 lists it; the assignment counts three DocTypes, this is the fourth). Hooks: `permission_query_conditions`, `has_permission`, `boot_session`. Shared logic: `prefill/exclusions.py`, `permissions.py`, `values.py`, `boot.py`.

Differences from the SPEC, and decisions the SPEC left open:
- The child field in Form Preset Excluded DocType is `excluded_doctype`, not `doctype` (SPEC 3.3). `doctype` is a reserved fieldname in Frappe.
- Scope Everyone is only usable while `allow_everyone_scope` is on. Turning it off later makes existing Everyone presets invisible to others, not just blocked on save (assignment: "usable by all, but only if the setting allows it").
- Shares only count while scope is Shared. Any share rows on a Private or Everyone preset are cleared on save.
- `permission_query_conditions` and `has_permission` both require read on the target DocType for non-System Manager users, as the assignment says. The owner of a preset therefore stops seeing it if they lose read on its target. System Manager sees everything.
- `has_permission` returns a real bool on every path: Frappe treats `None` from a controller hook as a denial.
- `field_count` is the number of captured fields plus the number of non-empty captured tables.
- Settings validation: `max_presets_per_user` must be 1 or more, `max_values_kb` must be 1 to 1024. There is no "0 means unlimited".
- Deleting a preset: Frappe copies the whole document into Deleted Document after `after_delete`. The controller blanks `values_json` in `after_delete`, so the copy holds no values. A restored preset would come back with empty values.
- Controller validation (not only `save_preset`) enforces scope rule, caps, unique title, excluded targets, create/write on the target, owner-only changes to scope/sharing/disabled, and the values shape. A direct REST or form save cannot bypass it.
- `values.py` checks shape only (version, keys, scalars, token names, `days` range, reserved keys). Allowlist against the target DocType's fields and token-to-fieldtype typing are step 3, with `get_capturable_fields`.

Tests: 32 pass on the dev site (permission matrix for owner, shared user, shared editor, role share, Everyone with the setting on and off, unrelated user, System Manager and Administrator; unreadable target; excluded targets; caps; Deleted Document scrub; values shape; boot flag).
Gates: ruff check and format clean, pre-commit clean, Semgrep 69 rules 0 findings.

## Step 3: API layer

Built `prefill/api.py` (six whitelisted functions as in SPEC 6), `fields.py` (SPEC 3.5 allowlist, token typing), `tokens.py` (server-side resolution), `apply.py` (the diff). The controller now also validates values against the target DocType, so a direct form or REST save cannot store a field the API would refuse.

Decisions and differences:
- Field permission uses `Meta.get_permlevel_access` directly, not `get_permitted_fields`. The latter returns column names plus system fields and does not list child tables, so it would still need the allowlist and a second lookup for tables. Capture checks the "read" permlevel, filling checks "write".
- `preview_apply`, `save_preset`, `record_use` and `delete_preset` are POST only. `preview_apply` is read-only in effect but takes the whole form document, and a GET would put business data in the URL and so in access logs.
- `record_use` counts with a query-builder update, not `doc.save`, so a shared user without write can still count a use, and `modified` does not move.
- `save_preset` keeps SPEC's default `scope="Private"`. A can_edit user updating a Shared preset must pass `scope="Shared"` again, otherwise the controller rejects it as a scope change. The Desk UI passes the current scope.
- The stored document decides draft status: `preview_apply` refuses if the client says docstatus is not 0 or the stored document's docstatus is not 0. A stored draft needs write on it, a new form needs create on the target.
- Fill rules: `fill_empty` treats None, empty string, and 0 on numeric and Check fields as empty (a new form always carries 0 for those). A value equal to the current one is reported as a skip, not a change. Datetime fields filled by `today` get 00:00:00.
- Link and Dynamic Link values are skipped if the record is missing or the user cannot read it. Exception: the `me` token (the user's own name). Dynamic Link is checked against the DocType the form will have after applying, so its Link-to-DocType partner is processed first.
- Consequence to know about: a Link to DocType needs read on that DocType record, which ordinary users do not have, so a Dynamic Link pair keyed on a DocType field is skipped for them. This is the SPEC rule applied as written.
- Rows in a table with no fillable cell are left out and a warning is returned.
- Controller order: target-DocType permission is checked before the values, so a user with no access gets a permission error, not a "field cannot be saved" one.
- `default_company` is only tested with mocks: it needs the Company DocType, which this site does not have (no ERPNext). Saving it on a Link to Company cannot be tested here either; the typing rule (Link with options Company) is in `fields.TOKEN_FITS`.
- Test DocTypes (`Prefill Test Doc`, `Prefill Test Row`) are created at test time as custom DocTypes and dropped in a class cleanup. DDL commits, so the cleanup rolls back first. They never ship in the app.

Tests: 66 pass. Gates: ruff, pre-commit, Semgrep 69 rules 0 findings (one finding on an ignored `has_permission` result was fixed).

## Step 4: Desk UI

`prefill/public/js/prefill.js`, included with `app_include_js`. Plain Desk JS, no build step. Boot flag now also carries `allow_everyone` (SPEC 7 lists `enabled` and `excluded` only) so the Save dialog can hide the Everyone option when the setting is off instead of failing on save.

Checked by hand in a real browser (Playwright, dev site, test DocType with a child table):
- `form-refresh` handler, `page.add_menu_item` ("Save as Preset") and `frm.add_custom_button` with the group "Presets" all render in v16. This closes the three step 1 items that were only verified at source level.
- Save dialog: title, description, scope, sharing table, field and child-table checklists. Pre-ticked = fields with a value; a 0 on a number or Check is a default, not a value.
- Apply: presets are loaded on click only, diff dialog with a checkbox per row, "fill empty only / overwrite" and "append / replace rows" re-run the server diff, skipped rows are greyed with the reason, nothing is written until Apply, applying leaves the form dirty and the normal save runs validations. `record_use` incremented `use_count`.
- No Presets button on a submitted document, and none on User (excluded) or on a Single DocType. "Save as Preset" is still offered on a submitted document (capturing from it is harmless).

Bugs the browser found that the server tests could not:
- Pre-tick offered an unchecked Check as "filled" (the client numeric list does not include Check).
- Select controls fire `change` during dialog construction with no value, which sent an empty mode and the server answered "Unknown mode". Changes are now ignored until the first diff has loaded.

Not built, needs a decision: there is no UI to put a dynamic value (`today`, `me`, ...) into a preset. The server stores, types and resolves them (steps 2 and 3, tested), but a user can only create one through the API. Options: a small "Make dynamic" choice next to eligible fields in the Save dialog, or leave it API-only for v0.1.

Gates: ESLint and Prettier pass (the repo `.eslintrc` now declares the `prefill` global), ruff, Semgrep 0 findings, 66 server tests.

## Not done yet

- GitHub CI (`ci.yml`, `linter.yml`) has not run: there is no remote. `linter.yml` only triggers on pull requests, so it needs a PR from `develop`. Creating the private remote needs the owner's go-ahead.
- Fresh-site install from README only (done after the README exists).
- `bench migrate` on a fresh v16 site and the CI run: not done for step 2 beyond the dev site.

## Open questions

- SPEC 12 Q2a: is a v16-only app accepted by the Compatibility audit and review.
- SPEC 12 Q3: demand check with 3 to 5 ERPNext users.
- Private repo (assignment) vs public GitHub (Marketplace): needs the owner's go-ahead before any public push.
- `requires-python = ">=3.14"` in the scaffold matches Frappe v16 (`>=3.14,<3.15`); confirm Frappe Cloud v16 images use 3.14.
