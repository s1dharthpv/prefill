# Prefill privacy policy

Prefill is an app that runs inside your own Frappe site. This page says what it does with data.

## What the app stores

When you save a preset, the values you chose are stored in your site's database, in a Form Preset record: a title, an optional description, who can use it, and the saved field values and child table rows. These values can be business data, such as customer names or prices. The app also keeps a use count and the date a preset was last used.

## Where the data goes

Nowhere outside your site. The app makes no external requests, sends no telemetry or analytics, and does not share data with the publisher or any third party. The publisher does not receive or have access to your data.

## Who can see it

- A private preset is visible to its owner and to System Managers
- A shared preset is also visible to the users and roles it is shared with
- An Everyone preset is visible to every user who may read the DocType, and only if an administrator has turned that on
- Access follows DocType permissions: a user who cannot read a DocType cannot see its presets. The exception is System Managers, who can see and manage every preset

## Logs and history

The app does not write preset values to the Error Log, to document version history, or to other logs. Requests the app rejects end as normal validation errors, which Frappe does not copy to the Error Log. If an unexpected server error ever happens, Frappe itself records the request in the Error Log, as it does for any app, so treat the Error Log as sensitive. When a preset is deleted, its values are removed from the Deleted Document copy that Frappe keeps.

## Retention and deletion

You decide how long presets are kept. Delete a preset to remove it. Presets are part of your site's database, so they are included in your site backups like any other data, and your backup policy applies to them.

## Your responsibilities as a site owner

Review who has sharing rights, keep Everyone sharing off unless you need it, and exclude any DocType that holds sensitive data from presets in Form Presets Settings.

## Contact

Questions about this policy: sidharth.thamban@gmail.com

Last updated: 2026-10-29
