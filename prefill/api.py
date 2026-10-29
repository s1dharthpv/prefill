import frappe
from frappe import _
from frappe.query_builder.functions import IfNull
from frappe.utils import cint, now_datetime

from prefill import fields
from prefill.apply import build_preview
from prefill.exclusions import get_settings, is_excluded

MODES = ("fill_empty", "overwrite")
TABLE_MODES = ("append", "replace")


@frappe.whitelist()
def get_capturable_fields(doctype: str) -> dict:
	"""Fields and child tables of `doctype` the current user may save in a preset."""
	_require_usable(doctype)
	frappe.has_permission(doctype, "read", throw=True)

	capturable = fields.get_capturable(doctype)
	return {
		"fields": [_describe(df) for df in capturable["fields"].values()],
		"tables": [
			{
				**_describe(entry["df"]),
				"child_doctype": entry["df"].options,
				"fields": [_describe(df) for df in entry["fields"].values()],
			}
			for entry in capturable["tables"].values()
		],
	}


@frappe.whitelist()
def list_presets(doctype: str) -> list[dict]:
	"""Enabled presets for `doctype` that the current user may use."""
	if not _usable(doctype) or not frappe.has_permission(doctype, "read"):
		return []

	presets = frappe.get_list(
		"Form Preset",
		filters={"target_doctype": doctype, "disabled": 0},
		fields=["name", "title", "description", "scope", "owner", "field_count", "use_count", "last_used"],
		order_by="title asc",
		limit_page_length=0,
	)
	for preset in presets:
		can_edit = frappe.has_permission("Form Preset", "write", doc=preset.name)
		preset["can_edit"] = bool(can_edit)

	return presets


@frappe.whitelist(methods=["POST"])
def save_preset(
	doctype: str,
	title: str,
	values: str | dict,
	scope: str = "Private",
	shares: str | list | None = None,
	description: str | None = None,
	name: str | None = None,
) -> str:
	"""Create a preset, or update the one called `name`. Returns its name."""
	_require_usable(doctype)

	values_json = values if isinstance(values, str) else frappe.as_json(values, indent=None)
	if isinstance(shares, str):
		shares = _parse_json(shares, _("Shares")) if shares.strip() else []
	if shares is not None and not (isinstance(shares, list) and all(isinstance(row, dict) for row in shares)):
		frappe.throw(_("Shares must be a list of rows"))

	if name:
		doc = frappe.get_doc("Form Preset", name)
		if doc.target_doctype != doctype:
			frappe.throw(_("A preset cannot move to another DocType"))
		doc.check_permission("write")
		doc.update({"title": title, "description": description, "values_json": values_json, "scope": scope})
		if shares is not None:
			doc.set("shares", shares)
		doc.save()
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Form Preset",
				"title": title,
				"target_doctype": doctype,
				"description": description,
				"scope": scope,
				"shares": shares or [],
				"values_json": values_json,
			}
		).insert()

	return doc.name


@frappe.whitelist(methods=["POST"])
def preview_apply(preset: str, doc: str | dict, mode: str = "fill_empty", table_mode: str = "append") -> dict:
	"""Diff of what applying `preset` to the form `doc` would change. Never writes the document.

	POST only: `doc` is business data and must not end up in a URL.
	"""
	_require_enabled()
	if mode not in MODES or table_mode not in TABLE_MODES:
		frappe.throw(_("Unknown mode"))
	if not isinstance(preset, str):
		frappe.throw(_("Choose a preset"))

	preset_doc = frappe.get_doc("Form Preset", preset)
	preset_doc.check_permission("read")
	if preset_doc.disabled:
		frappe.throw(_("This preset is disabled"))

	target = preset_doc.target_doctype
	_require_usable(target)

	doc = _parse_json(doc, _("The form")) if isinstance(doc, str) else doc
	if not isinstance(doc, dict) or doc.get("doctype") != target:
		frappe.throw(_("This preset is for {0}").format(frappe.bold(target)))

	_require_draft(target, doc)

	return build_preview(preset_doc, doc, mode, table_mode)


@frappe.whitelist(methods=["POST"])
def record_use(preset: str):
	"""Count one use of `preset`. Anyone who may use it may count it, so this skips the write permission."""
	_require_enabled()
	frappe.has_permission("Form Preset", "read", doc=preset, throw=True)

	table = frappe.qb.DocType("Form Preset")
	(
		frappe.qb.update(table)
		.set(table.use_count, IfNull(table.use_count, 0) + 1)
		.set(table.last_used, now_datetime())
		.where(table.name == preset)
		.run()
	)


@frappe.whitelist(methods=["POST"])
def delete_preset(name: str):
	frappe.delete_doc("Form Preset", name)


def _parse_json(raw: str, label: str):
	"""Bad client input must end as a validation error. An unexpected exception would make Frappe
	copy the whole request, values included, into the Error Log."""
	try:
		return frappe.parse_json(raw)
	except ValueError, RecursionError:
		frappe.throw(_("{0} is not valid JSON").format(label))


def _describe(df) -> dict:
	described = {"fieldname": df.fieldname, "label": df.label or df.fieldname, "fieldtype": df.fieldtype}
	if df.fieldtype == "Link":
		described["options"] = df.options  # which dynamic values fit a Link depends on its target
	return described


def _usable(doctype: str) -> bool:
	return bool(get_settings().enabled and frappe.db.exists("DocType", doctype) and not is_excluded(doctype))


def _require_enabled():
	if not get_settings().enabled:
		frappe.throw(_("Presets are turned off"))


def _require_usable(doctype: str):
	_require_enabled()
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} does not exist").format(frappe.bold(doctype)))
	if is_excluded(doctype):
		frappe.throw(_("Presets cannot be used on {0}").format(frappe.bold(doctype)))


def _require_draft(target: str, doc: dict):
	"""A preset only fills new or draft documents. The stored document decides, not the client."""
	name = doc.get("name")
	name = name if isinstance(name, str) else None
	stored = bool(name) and frappe.db.exists(target, name)

	if cint(doc.get("docstatus")) != 0 or (stored and frappe.db.get_value(target, name, "docstatus") != 0):
		frappe.throw(_("Presets can only be applied to new or draft documents"))

	frappe.has_permission(target, "write" if stored else "create", doc=name if stored else None, throw=True)
