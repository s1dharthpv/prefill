import frappe
from frappe.model import CORE_DOCTYPES

# DocTypes where saving presets makes no sense or would be unsafe, on top of
# frappe.model.CORE_DOCTYPES and anything an admin adds in Form Presets Settings.
APP_EXCLUDED_DOCTYPES = frozenset(
	{
		"User",
		"Role",
		"Has Role",
		"DocPerm",
		"Custom DocPerm",
		"User Permission",
		"Form Preset",
		"Form Preset Share",
		"Form Presets Settings",
		"Form Preset Excluded DocType",
	}
)


def get_settings():
	return frappe.get_cached_doc("Form Presets Settings")


def get_excluded_doctypes() -> set[str]:
	"""Names excluded by list. Single, child table and virtual DocTypes are checked by `is_excluded`."""
	configured = {row.excluded_doctype for row in get_settings().excluded_doctypes if row.excluded_doctype}
	return set(CORE_DOCTYPES) | APP_EXCLUDED_DOCTYPES | configured


def is_excluded(doctype: str) -> bool:
	if doctype in get_excluded_doctypes():
		return True

	meta = frappe.get_meta(doctype)
	return bool(meta.issingle or meta.istable or meta.is_virtual)
