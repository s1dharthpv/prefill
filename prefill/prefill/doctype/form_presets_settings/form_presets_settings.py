import frappe
from frappe import _
from frappe.model.document import Document

MAX_VALUES_KB_LIMIT = 1024


class FormPresetsSettings(Document):
	def validate(self):
		if (self.max_presets_per_user or 0) < 1:
			frappe.throw(_("Max Presets Per User must be at least 1"))

		if not 1 <= (self.max_values_kb or 0) <= MAX_VALUES_KB_LIMIT:
			frappe.throw(_("Max Values Size must be between 1 and {0} KB").format(MAX_VALUES_KB_LIMIT))

		seen = set()
		for row in self.excluded_doctypes:
			if row.excluded_doctype in seen:
				frappe.throw(_("Row {0}: {1} is listed twice").format(row.idx, row.excluded_doctype))
			seen.add(row.excluded_doctype)
