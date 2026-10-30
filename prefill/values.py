import json

import frappe
from frappe import _

VERSION = 1
MAX_DAYS_OFFSET = 3650

# A named tuple, not `except A, B:` (see COERCE_ERRORS in apply.py for why).
# RecursionError is what the json module raises for deeply nested input.
PARSE_ERRORS = (ValueError, RecursionError)

# token -> whether it takes a `days` offset
TOKENS = {
	"today": True,
	"now": False,
	"month_start": False,
	"month_end": False,
	"me": False,
	"default_company": False,
}

# Never stored in a preset row, whatever the child DocType says.
RESERVED_KEYS = frozenset(
	{"name", "idx", "owner", "creation", "modified", "modified_by", "docstatus", "doctype"}
)


def is_reserved_key(key: str) -> bool:
	return key in RESERVED_KEYS or key.startswith("parent")


def parse(raw: str | None) -> dict:
	"""Parse and shape-check `values_json`. Field level checks against the target DocType live elsewhere."""
	try:
		values = json.loads(raw or "")
	except PARSE_ERRORS:
		frappe.throw(_("Preset values are not valid JSON"))

	if not isinstance(values, dict) or set(values) - {"version", "fields", "tables"}:
		frappe.throw(_("Preset values must be an object with only version, fields and tables"))

	if values.get("version") != VERSION:
		frappe.throw(_("Unsupported preset values version"))

	fields = values.setdefault("fields", {})
	tables = values.setdefault("tables", {})
	if not isinstance(fields, dict) or not isinstance(tables, dict):
		frappe.throw(_("Preset fields and tables must be objects"))

	for key, value in fields.items():
		_check_cell(key, value)

	for table, rows in tables.items():
		if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
			frappe.throw(_("Rows of table {0} must be a list of objects").format(table))
		for row in rows:
			for key, value in row.items():
				_check_cell(key, value)

	if not fields and not any(tables.values()):
		frappe.throw(_("A preset needs at least one field value or table row"))

	return values


def count_entries(values: dict) -> int:
	return len(values["fields"]) + len([rows for rows in values["tables"].values() if rows])


def _check_cell(key, value):
	if not isinstance(key, str) or not key or is_reserved_key(key):
		frappe.throw(_("{0} cannot be stored in a preset").format(frappe.bold(str(key))))

	if isinstance(value, dict):
		_check_token(key, value)
	elif value is None or not isinstance(value, str | int | float | bool):
		frappe.throw(_("The value of {0} must be a plain text, number or Yes/No value").format(key))


def _check_token(key: str, value: dict):
	token = value.get("$dyn")
	if token not in TOKENS:
		frappe.throw(_("{0} uses an unknown dynamic value").format(key))

	extra = set(value) - {"$dyn", "days"}
	if extra or ("days" in value and not TOKENS[token]):
		frappe.throw(_("The dynamic value of {0} has options it does not support").format(key))

	days = value.get("days")
	if "days" in value and (
		isinstance(days, bool) or not isinstance(days, int) or abs(days) > MAX_DAYS_OFFSET
	):
		frappe.throw(
			_("The days offset of {0} must be a whole number between -{1} and {1}").format(
				key, MAX_DAYS_OFFSET
			)
		)
