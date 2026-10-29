import frappe
from frappe import _
from frappe.model import child_table_fields, default_fields

# SPEC 3.5. Table is listed because child tables are captured as rows, not as a value.
ALLOWED_FIELDTYPES = frozenset(
	{
		"Data",
		"Link",
		"Dynamic Link",
		"Select",
		"Int",
		"Float",
		"Currency",
		"Percent",
		"Check",
		"Date",
		"Datetime",
		"Time",
		"Duration",
		"Small Text",
		"Text",
		"Long Text",
		"Text Editor",
		"Rating",
		"Autocomplete",
		"Phone",
		"Table",
	}
)

SYSTEM_FIELDS = frozenset(default_fields) | frozenset(child_table_fields) | {"amended_from"}

# token -> does the field fit
TOKEN_FITS = {
	"today": lambda df: df.fieldtype in ("Date", "Datetime"),
	"now": lambda df: df.fieldtype == "Datetime",
	"month_start": lambda df: df.fieldtype == "Date",
	"month_end": lambda df: df.fieldtype == "Date",
	"me": lambda df: df.fieldtype == "Data" or (df.fieldtype == "Link" and df.options == "User"),
	"default_company": lambda df: df.fieldtype == "Link" and df.options == "Company",
}


def field_problem(df) -> str | None:
	"""Why a field can never be captured or filled, whoever the user is. None if it can."""
	if df.fieldtype not in ALLOWED_FIELDTYPES:
		return _("This type of field cannot be filled")
	if df.fieldname in SYSTEM_FIELDS:
		return _("This is a system field")
	if df.is_virtual:
		return _("This is a virtual field")
	if df.fetch_from:
		return _("This field is fetched from another field")
	if df.read_only:
		return _("This field is read only")
	return None


def permitted_levels(meta, ptype: str, user: str | None = None, parenttype: str | None = None) -> set[int]:
	return set(meta.get_permlevel_access(permission_type=ptype, parenttype=parenttype, user=user))


def has_level(df, levels: set[int]) -> bool:
	return (df.permlevel or 0) in levels


def get_capturable(doctype: str, ptype: str = "read", user: str | None = None) -> dict:
	"""Fields and child tables of `doctype` the user may capture (ptype "read") or fill (ptype "write").

	Returns {"fields": {fieldname: df}, "tables": {fieldname: {"df": df, "fields": {fieldname: df}}}}.
	"""
	meta = frappe.get_meta(doctype)
	levels = permitted_levels(meta, ptype, user)

	fields = {}
	tables = {}
	for df in meta.fields:
		if field_problem(df) or not has_level(df, levels):
			continue

		if df.fieldtype != "Table":
			fields[df.fieldname] = df
			continue

		child_meta = frappe.get_meta(df.options)
		if child_meta.is_virtual:
			continue

		child_levels = permitted_levels(child_meta, ptype, user, parenttype=doctype)
		tables[df.fieldname] = {
			"df": df,
			"fields": {
				child_df.fieldname: child_df
				for child_df in child_meta.fields
				if child_df.fieldtype != "Table"
				and not field_problem(child_df)
				and has_level(child_df, child_levels)
			},
		}

	return {"fields": fields, "tables": tables}


def validate_values(doctype: str, values: dict):
	"""Check a parsed preset against what the current user may capture on `doctype`.

	Messages name fields only, never values.
	"""
	capturable = get_capturable(doctype)

	for fieldname, value in values["fields"].items():
		df = capturable["fields"].get(fieldname)
		if not df:
			frappe.throw(_("{0} cannot be saved in a preset for {1}").format(frappe.bold(fieldname), doctype))
		_check_token_fits(df, value)

	for table, rows in values["tables"].items():
		entry = capturable["tables"].get(table)
		if not entry:
			frappe.throw(
				_("Table {0} cannot be saved in a preset for {1}").format(frappe.bold(table), doctype)
			)

		for row in rows:
			for fieldname, value in row.items():
				df = entry["fields"].get(fieldname)
				if not df:
					frappe.throw(
						_("{0} cannot be saved in the rows of {1}").format(frappe.bold(fieldname), table)
					)
				_check_token_fits(df, value)


def _check_token_fits(df, value):
	if isinstance(value, dict) and not TOKEN_FITS[value["$dyn"]](df):
		frappe.throw(
			_("The dynamic value {0} cannot be used on field {1}").format(
				frappe.bold(value["$dyn"]), frappe.bold(df.fieldname)
			)
		)
