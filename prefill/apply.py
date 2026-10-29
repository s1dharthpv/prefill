import math

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, get_time, getdate

from prefill import tokens
from prefill.fields import field_problem, has_level, permitted_levels

NUMERIC_FIELDTYPES = ("Int", "Float", "Currency", "Percent", "Check")


def build_preview(preset, doc: dict, mode: str, table_mode: str) -> dict:
	"""Work out what applying `preset` to `doc` would change. Reads only, never writes the document."""
	target = preset.target_doctype
	meta = frappe.get_meta(target)
	values = frappe.parse_json(preset.values_json)
	levels = permitted_levels(meta, "write")

	changes = plan_cells(meta, values["fields"], levels, doc, mode)
	warnings = []
	tables = []

	for fieldname, rows in values["tables"].items():
		rows_now = doc.get(fieldname)
		entry = {
			"fieldname": fieldname,
			"label": fieldname,
			"mode": table_mode,
			"action": "set",
			"reason": None,
			"current_rows": len(rows_now) if isinstance(rows_now, list) else 0,
			"rows": [],
		}
		tables.append(entry)

		table_df = meta.get_field(fieldname)
		reason = _table_problem(table_df, levels)
		if table_df:
			entry["label"] = table_df.label or fieldname
		if reason:
			entry.update(action="skip", reason=reason)
			continue

		child_meta = frappe.get_meta(table_df.options)
		child_levels = permitted_levels(child_meta, "write", parenttype=target)
		for index, row in enumerate(rows, start=1):
			cells = plan_cells(child_meta, row, child_levels, {}, "overwrite")
			filled = {cell["fieldname"]: cell["new"] for cell in cells if cell["action"] == "set"}
			skipped = [cell for cell in cells if cell["action"] == "skip"]
			if not filled:
				warnings.append(
					_("Row {0} of {1} was left out: none of its values could be filled").format(
						index, entry["label"]
					)
				)
				continue
			entry["rows"].append({"values": filled, "skipped": skipped})

	return {"changes": changes, "tables": tables, "warnings": warnings}


def plan_cells(meta, cells: dict, levels: set[int], current: dict, mode: str) -> list[dict]:
	"""Decide, cell by cell, what to set. `current` holds the existing values, `mode` is fill_empty or overwrite."""
	known = dict(current)
	planned = []

	# Dynamic Link fields depend on the value of the Link field that names their DocType.
	ordered = sorted(cells.items(), key=lambda item: _is_dynamic_link(meta.get_field(item[0])))
	for fieldname, raw in ordered:
		df = meta.get_field(fieldname)
		change = {
			"kind": "field",
			"fieldname": fieldname,
			"label": (df.label if df else None) or fieldname,
			"current": _plain(current.get(fieldname)),
			"new": None,
			"action": "skip",
			"reason": None,
		}
		planned.append(change)

		reason = _field_problem(df, levels)
		if reason:
			change["reason"] = reason
			continue

		value, reason = _prepare(df, raw, known)
		if reason:
			change["reason"] = reason
			continue

		change["new"] = value
		if _same(df, current.get(fieldname), value):
			change["reason"] = _("Already has this value")
		elif mode == "fill_empty" and not _is_empty(df, current.get(fieldname)):
			change["reason"] = _("Already has a value")
		else:
			change["action"] = "set"
			known[fieldname] = value

	return planned


def _field_problem(df, levels: set[int]) -> str | None:
	if not df:
		return _("This field no longer exists")
	if reason := field_problem(df):
		return reason
	if not has_level(df, levels):
		return _("You cannot edit this field")
	return None


def _table_problem(df, levels: set[int]) -> str | None:
	if not df or df.fieldtype != "Table":
		return _("This table no longer exists")
	if reason := field_problem(df):
		return reason
	if not has_level(df, levels):
		return _("You cannot edit this table")
	if frappe.get_meta(df.options).is_virtual:
		return _("This table cannot be filled")
	return None


def _is_dynamic_link(df) -> bool:
	return bool(df and df.fieldtype == "Dynamic Link")


def _prepare(df, raw, known: dict) -> tuple[str | int | float | None, str | None]:
	trusted = False
	value = raw
	if isinstance(raw, dict):
		value, reason = tokens.resolve(raw, df)
		if reason:
			return None, reason
		trusted = raw["$dyn"] == "me"  # the user's own name is not worth a read check

	if value == "":
		return None, _("The saved value is empty")

	try:
		value = coerce(df, value)
	except ValueError, TypeError, frappe.ValidationError:
		return None, _("The saved value does not fit this field")

	return value, _reference_problem(df, value, known, trusted)


def _reference_problem(df, value, known: dict, trusted: bool) -> str | None:
	if df.fieldtype == "Select":
		options = [option.strip() for option in (df.options or "").split("\n")]
		if value not in options:
			return _("This option is no longer available")

	elif df.fieldtype in ("Link", "Dynamic Link"):
		linked = df.options if df.fieldtype == "Link" else known.get(df.options)
		if not linked:
			return _("Choose the linked type first")
		if not frappe.db.exists("DocType", linked) or not frappe.db.exists(linked, value):
			return _("The linked record no longer exists")
		if not trusted and not _can_read(linked, value):
			return _("You cannot read the linked record")

	return None


def _can_read(linked: str, value) -> bool:
	"""May the user read what a Link points at? A Link to DocType names a DocType, and what matters is
	whether the user can read documents of that DocType (a Payment Entry party type, for example),
	not whether they can read the DocType definition itself, which ordinary users cannot."""
	if linked == "DocType":
		return bool(frappe.has_permission(value, "read"))
	return bool(frappe.has_permission(linked, "read", doc=value))


def coerce(df, value):
	"""Make `value` fit the field, or raise ValueError."""
	fieldtype = df.fieldtype

	if fieldtype == "Check":
		if str(value) in ("0", "1", "True", "False") or isinstance(value, bool):
			return int(str(value) in ("1", "True"))
		raise ValueError

	if fieldtype == "Int":
		number = _number(value)
		if not number.is_integer():
			raise ValueError
		return int(number)

	if fieldtype in ("Float", "Currency", "Percent", "Duration"):
		return _number(value)

	if fieldtype == "Rating":
		number = _number(value)
		if not 0 <= number <= 1:
			raise ValueError
		return number

	if fieldtype == "Date":
		return str(_required(getdate(_text(value))))

	if fieldtype == "Datetime":
		return str(_required(get_datetime(_text(value))))

	if fieldtype == "Time":
		return str(_required(get_time(_text(value))))

	if isinstance(value, bool):
		raise ValueError

	return value if isinstance(value, str) else str(value)


def _number(value) -> float:
	if not isinstance(value, bool | int | float | str):
		raise ValueError
	number = float(value)
	if not math.isfinite(number):
		raise ValueError
	return number


def _text(value) -> str:
	if not isinstance(value, str):
		raise ValueError
	return value


def _required(value):
	if value is None:
		raise ValueError
	return value


def _is_empty(df, current) -> bool:
	if current is None or current == "":
		return True
	return df.fieldtype in NUMERIC_FIELDTYPES and flt(current) == 0


def _same(df, current, new) -> bool:
	if current is None or current == "":
		return False
	if df.fieldtype in NUMERIC_FIELDTYPES:
		return flt(current) == flt(new)
	return str(current) == str(new)


def _plain(value):
	if value is None or isinstance(value, str | int | float | bool):
		return value
	return str(value)
