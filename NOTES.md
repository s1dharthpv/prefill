# Design notes

How Prefill behaves and why. The [README](README.md) is the user guide; this file is for people reading or changing the code.

## Layout

| Path | What it holds |
|---|---|
| `prefill/prefill/doctype/` | Form Preset, Form Preset Share (child), Form Presets Settings (Single), Form Preset Excluded DocType (child) |
| `prefill/api.py` | The whitelisted functions: `get_capturable_fields`, `list_presets`, `save_preset`, `preview_apply`, `record_use`, `delete_preset` |
| `prefill/permissions.py` | `has_permission` and `permission_query_conditions` for Form Preset |
| `prefill/fields.py` | Which fields can be saved or filled, and which dynamic values fit which field |
| `prefill/values.py` | Shape check of the saved values (`values_json`) |
| `prefill/tokens.py` | Resolves dynamic values on the server |
| `prefill/apply.py` | Builds the preview diff, without writing anything |
| `prefill/exclusions.py`, `prefill/boot.py` | Excluded DocTypes, and the boot flag that tells the desk whether to show the UI |
| `prefill/public/js/prefill.js` | Desk UI. Plain JS, no build step |
| `ui_tests/smoke.py` | Browser smoke test of the whole flow (not part of `bench run-tests`) |
| `docs/` | Support, privacy and terms pages, the screenshots in `docs/images/` and the demo video in `docs/demo/` |

Frappe v16 only. The app uses no `override_doctype_class`, no `override_whitelisted_methods` and no wildcard `doc_events`, and declares no dependency other than Frappe.

## Permissions

- The rules are in the README table. They are enforced by the `has_permission` and `permission_query_conditions` hooks, and by the Form Preset controller for the things a hook cannot see (changing scope, sharing or disabled).
- A user needs read on the target DocType to see or apply a preset, create to save one, and write to change its values. System Managers see, apply, disable and delete every preset without the target read check, but saving a preset or changing its values still needs create or write on the target. The read check also applies to a preset's own owner: an owner who loses read on the target cannot delete or disable it.
- `has_permission` returns a real boolean on every path. Frappe treats `None` from a controller hook as a denial.
- Shares only count while the scope is Shared. Share rows on a Private or Everyone preset are cleared on save.
- Scope Everyone is only usable while Allow Everyone Scope is on. Turning it off later hides existing Everyone presets from everyone but their owner and System Managers. The owner can still edit them; choosing Everyone is what is refused.
- Validation lives in the controller, not only in `save_preset`, so a direct form or REST save cannot bypass scope rules, caps, exclusions, the target permission checks or the values checks.

## What is saved and filled

- The allowed field types are an allowlist (`ALLOWED_FIELDTYPES` in `fields.py`). Password, Attach, Attach Image, Code, JSON and similar types are not on it.
- Read-only fields, fields with `fetch_from`, virtual fields and system fields are refused at save and again when applying. So are fields above the user's permission level: capture checks the read level, filling checks the write level, using `Meta.get_permlevel_access`.
- Reserved row keys (`name`, `idx`, anything starting with `parent`) are never stored.
- Hidden fields are included unless they are read-only or fetched, because hidden but set fields such as a naming series are common.
- `values_json` is JSON version 1: `fields`, and `tables` holding rows of plain values or dynamic value objects. It is hidden in the form and edited only through the dialog.
- `field_count` is the number of saved fields plus the number of non-empty saved tables.

## Applying a preset

- `preview_apply` never writes the document. It takes the form's current values only to compute the diff, and the client then sets values with `frm.set_value` and `frm.add_child`, so the normal save and its validations run.
- It refuses unless the form is new or a draft. The stored document decides: the server checks both the docstatus the client sent and the stored one. A stored draft needs write on it, a new form needs create on the target DocType.
- `fill_empty` treats None, an empty string, and 0 on number and Check fields as empty, because a new form carries 0 for those. A value equal to the current one is reported as a skip, not a change.
- A Link or Dynamic Link value is skipped if the record is missing or the user cannot read it (the Current user value is exempt). A Select value is skipped if the option is gone. A Dynamic Link is checked against the DocType the form will have after applying.
- A Link to DocType names a DocType, so what is checked is whether the user can read documents of that DocType, not the DocType definition (which ordinary users cannot read). This is what lets a Payment Entry party type, and the party that depends on it, be filled by an ordinary Accounts user.
- A child row with no fillable cell is left out and a warning is returned.
- `record_use` counts with a query-builder update, so a user who may use a preset but not write it still counts a use, and `modified` does not move.

## Dynamic values

- A dynamic row replaces the fixed value of its field. The preset stores a small object such as `{"$dyn": "today", "days": 7}`, never a resolved date.
- Values are resolved on the server in the site's time zone each time a preset is applied. Today on a Datetime field gives midnight.
- Which values fit which field is `TOKEN_FITS` in `fields.py`, enforced on save. The dialog copies those rules in `prefill.DYNAMIC_VALUES` so it only offers fitting fields; if the two drift, the server refuses the save.
- Default company needs the Company DocType and a default company; otherwise the field is skipped with a reason.
- The server accepts dynamic values in child table rows. The dialog does not offer them.

## Data handling

- No network calls, no telemetry. Form Preset has `track_changes` off, so values do not enter version history. Nothing in the app writes values to a log.
- Frappe copies a deleted document into Deleted Document right after `after_delete`. The controller blanks `values_json` in `after_delete`, so the copy holds no values and a restored preset would come back empty.
- Bad input ends as a validation error, which Frappe does not copy to the Error Log (except in developer mode, where it logs them too): invalid or too deeply nested JSON, wrong shapes for `shares`, `doc` or `preset`, a posted table that is not a list. Wrong argument types are stopped by Frappe's own type check, which answers 417 and is not logged outside developer mode. If an unexpected server error ever happens, Frappe records the request in the Error Log, as for any app, so treat that log as sensitive.
- `preview_apply`, `save_preset`, `record_use` and `delete_preset` are POST only, so form data never appears in a URL or an access log.

## Limits worth knowing

- Desk only; presets fill new and draft documents only.
- Child tables are saved through their parent. Single, child table, virtual and core system DocTypes are excluded.
- Dynamic values are not offered for child table rows in the dialog.
- `save_preset` makes a new preset Private unless `scope` is given. When updating, `scope`, `shares` and `description` that are left out mean "unchanged", so a partial update cannot silently reset sharing. Pass an empty `description` to clear it.

## Tests and checks

- Server tests: 69, run with `bench --site <site> run-tests --app prefill`. They cover the permission matrix, the allowlist, token typing, caps, exclusions, the preview in each mode, malformed input, the Deleted Document scrub and the boot flag.
- Test DocTypes (`Prefill Test Doc`, `Prefill Test Row`) are created as custom DocTypes at test time and dropped afterwards. Creating them commits, so the cleanup rolls back first. They never ship in the app.
- The default company value is only tested with mocks, because it needs a Company DocType that a bare Frappe site does not have.
- `ui_tests/smoke.py` drives the real flow in a browser: save a preset with a child table, apply it, check the preview in each mode, save, and check that a submitted document gets no Apply button and an excluded DocType gets no Presets UI. Its header explains how to run it.
- CI runs the server tests on pushes to `develop` or `main` and on pull requests, and the linters (pre-commit, the Frappe Semgrep rules, pip-audit) on pull requests.
- `pyproject.toml` requires Python `>=3.14`, which is what Frappe v16 requires.
