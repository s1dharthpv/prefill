import frappe

PARENT = "Prefill Test Doc"
CHILD = "Prefill Test Row"

_PERMS = {"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1}


def _field(fieldname, fieldtype, **kwargs):
	return {
		"fieldname": fieldname,
		"label": fieldname.replace("_", " ").title(),
		"fieldtype": fieldtype,
		**kwargs,
	}


def create_test_doctypes():
	"""Custom DocTypes with one field of every kind the allowlist treats differently."""
	drop_test_doctypes()

	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": CHILD,
			"module": "Prefill",
			"custom": 1,
			"istable": 1,
			"fields": [
				_field("item_code", "Data"),
				_field("qty", "Int"),
				_field("rate", "Currency"),
				_field("link_user", "Link", options="User"),
				_field("ref_type", "Link", options="DocType"),
				_field("ref_name", "Dynamic Link", options="ref_type"),
				_field("secret", "Password"),
				_field("fetched", "Data", fetch_from="link_user.full_name"),
				_field("locked", "Data", read_only=1),
			],
		}
	).insert()

	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": PARENT,
			"module": "Prefill",
			"custom": 1,
			"is_submittable": 1,
			"fields": [
				_field("title", "Data"),
				_field("status", "Select", options="Draft\nOpen\nClosed", default="Draft"),
				_field("priority", "Select", options="\nLow\nHigh"),
				_field("due_date", "Date"),
				_field("start_at", "Datetime"),
				_field("qty", "Int"),
				_field("rate", "Currency"),
				_field("flag", "Check"),
				_field("owner_user", "Link", options="User"),
				_field("ref_type", "Link", options="DocType"),
				_field("ref_name", "Dynamic Link", options="ref_type"),
				_field("restricted_link", "Link", options="Error Log"),
				_field("notes", "Small Text"),
				_field("secret", "Password"),
				_field("attachment", "Attach"),
				_field("picture", "Attach Image"),
				_field("snippet", "Code"),
				_field("locked", "Data", read_only=1),
				_field("fetched", "Data", fetch_from="owner_user.full_name"),
				_field("hidden_note", "Data", hidden=1),
				_field("restricted", "Data", permlevel=1),
				_field("items", "Table", options=CHILD),
				_field("restricted_items", "Table", options=CHILD, permlevel=1),
			],
			"permissions": [
				{"role": "Desk User", "permlevel": 0, **_PERMS},
				{"role": "System Manager", "permlevel": 0, **_PERMS},
				{"role": "System Manager", "permlevel": 1, "read": 1, "write": 1},
			],
		}
	).insert()


def drop_test_doctypes():
	# DDL commits, so anything open is committed by the drop. Callers roll back first.
	for name in (PARENT, CHILD):
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True)
	frappe.db.commit()
