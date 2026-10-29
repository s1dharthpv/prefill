# Prefill

Save the values of a form as a preset, then fill a new form with it in one click. A preview shows exactly what will change before anything is filled.

Example: you create the same customer's invoice every week. Fill it once, choose Menu > Save as Preset, and next week choose Presets > Apply a Preset on the new invoice.

## Requirements

- Frappe v16 (Python 3.14)
- No other app. Prefill works on standard DocTypes, including your own. A few kinds are left out (see below).

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench --site $YOUR_SITE install-app prefill
```

## Using it

**Save a preset.** Fill a form, then Menu > Save as Preset. Give it a title, choose who can use it (scope), and tick the fields and child tables to keep. Fields that have a value are ticked for you. Only ticked values are saved.

**Dynamic values.** Under "Dynamic values (optional)" in the same dialog, pick a field and a value that is worked out each time the preset is applied, instead of saving a fixed one. It replaces the saved value of that field, ticked or not. Each value only appears for the fields it fits:

| Value | Fits | Notes |
|---|---|---|
| Today | Date, Datetime | optional "days from today", positive or negative, up to 3650. On a Datetime field it fills midnight |
| Now | Datetime | |
| First day of this month, Last day of this month | Date | |
| Current user | Data, or a Link to User | |
| Default company | a Link to Company | filled only if the user has a default company; skipped with a reason otherwise |

Dynamic values work on the fields of the form itself, not on child table rows.

**Apply a preset.** On a new or draft form, click Presets > Apply a Preset and pick one. A preview opens:

- one row per field, with the current value, the preset value and a checkbox
- "Fill empty fields only" (default) keeps what you typed; "Overwrite existing values" replaces it
- "Append rows" (default) adds the preset's rows to a child table; "Replace rows" clears it first
- rows that cannot be filled are greyed out with the reason (the linked record no longer exists, the option is gone, you cannot edit that field)

Nothing is written until you click Apply, and applying only changes the form on screen. You then save the form as usual, so every normal validation runs.

**Scope.** Private (only you), Shared (chosen users and roles, each with an optional "can edit"), or Everyone (off until a System Manager allows it in Form Presets Settings; if it is turned off later, existing Everyone presets stay with their owner and System Managers and other users stop seeing them). Presets are also listed under Form Preset in the Prefill workspace.

**Who can do what.**

| | Owner | Shared user | Shared with "can edit" | Everyone scope | System Manager |
|---|---|---|---|---|---|
| See and apply | yes | yes | yes | yes | yes |
| Edit title, description, values | yes | no | yes | no | yes |
| Change scope or sharing | yes | no | no | no | yes |
| Disable or enable | yes | no | no | no | yes |
| Delete | yes | no | no | no | yes |

On top of this, a user needs read permission on the target DocType to see or apply a preset, create permission to save one, and write permission to change its values. System Managers see and manage every preset, whatever their access to the target DocType.

## What is never saved or filled

Password, Attach, Attach Image, Signature, Barcode, Geolocation, Image, Code, HTML, JSON and similar fields; read-only fields; fields filled from another field (fetch from); virtual fields; system fields (name, owner, docstatus and the like); and fields you do not have permission to read.

Presets are not offered on core system DocTypes, User, Role and permission DocTypes, Single DocTypes, child tables (they are saved through their parent) and virtual DocTypes. A System Manager can exclude more DocTypes in Form Presets Settings.

## Settings

Form Presets Settings (System Manager only):

| Setting | Default | Meaning |
|---|---|---|
| Enabled | on | Turns the Presets buttons on or off for everyone |
| Allow Everyone Scope | off | Lets presets be shared with every user |
| Max Presets Per User | 200 | Cap checked when a preset is created |
| Max Values Size (KB) | 64 | Cap on the saved values of one preset |
| Excluded DocTypes | none | Added to the built-in exclusions |

## Limits

- Desk only. There is no portal or website form support, and no mobile app.
- Presets fill new and draft documents only. Submitted and cancelled documents are refused by the server, not just hidden in the interface.
- A preset keeps plain values. It does not run expressions or templates.
- Dynamic values are resolved on the server in the site's time zone when a preset is applied, and checked against the field type when it is saved. They are not offered for child table rows.
- A Link field is filled only if the linked record still exists and you may read it. A Select is filled only if the option still exists.

## Data handling

- Preset values can contain business data. They stay on your site: the app makes no external calls and sends no telemetry.
- The app does not write values to logs, to the Error Log, or to document version history. Deleting a preset removes its values from the Deleted Document copy as well.
- Requests the app rejects (bad input, no permission) end as normal validation errors, which Frappe does not copy to the Error Log. If an unexpected server error ever happens, Frappe itself records the request in the Error Log, as it does for any app, so treat the Error Log as sensitive.
- Retention is up to you: delete presets you no longer need, and review who has Everyone or Shared access.
- Admin checklist: keep Allow Everyone Scope off unless needed; review Excluded DocTypes for DocTypes holding sensitive data; review Form Preset records and their scope before offboarding a user.

## Development

```bash
bench --site $YOUR_SITE set-config allow_tests true
bench --site $YOUR_SITE run-tests --app prefill
```

Lint and format with `pre-commit` (ruff, eslint, prettier):

```bash
cd apps/prefill
pre-commit install
```

Frappe's [Semgrep rules](https://github.com/frappe/semgrep-rules) run in CI on pull requests and must stay at zero findings:

```bash
git clone --depth 1 https://github.com/frappe/semgrep-rules.git frappe-semgrep-rules
semgrep --config ./frappe-semgrep-rules/rules --config r/python.lang.correctness .
```

A browser smoke test of the whole save and apply flow lives in `ui_tests/smoke.py`; its header explains how to run it.

CI: server tests run on every push to `develop`; linters run on every pull request.

## Support, privacy and terms

- [Support](docs/SUPPORT.md)
- [Privacy policy](docs/PRIVACY.md)
- [Terms of use](docs/TERMS.md)

## License

MIT. See `LICENSE`.
