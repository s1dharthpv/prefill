import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from prefill import fields, values
from prefill.exclusions import get_settings, is_excluded
from prefill.permissions import is_system_manager


class FormPreset(Document):
	def validate(self):
		self.validate_target()
		self.validate_scope()
		self.validate_shares()
		self.validate_owner_only_changes()
		self.validate_title()
		self.validate_target_permission()
		self.validate_values()
		self.validate_user_cap()

	def after_delete(self):
		# Frappe copies the whole document into Deleted Document right after this hook,
		# so the values are dropped first. The values are business data and must not be kept there.
		self.values_json = None

	def validate_target(self):
		if not frappe.db.exists("DocType", self.target_doctype):
			frappe.throw(_("DocType {0} does not exist").format(frappe.bold(self.target_doctype)))

		if is_excluded(self.target_doctype):
			frappe.throw(_("Presets cannot be used on {0}").format(frappe.bold(self.target_doctype)))

	def validate_scope(self):
		if self.scope == "Everyone" and not get_settings().allow_everyone_scope:
			frappe.throw(_("Sharing with everyone is turned off in Form Presets Settings"))

	def validate_shares(self):
		if self.scope != "Shared":
			self.shares = []
			return

		if not self.shares:
			frappe.throw(_("Add at least one user or role to share this preset with"))

		for row in self.shares:
			if row.share_type == "User":
				row.role = None
				if not row.user:
					frappe.throw(_("Row {0}: select a user").format(row.idx))
			else:
				row.user = None
				if not row.role:
					frappe.throw(_("Row {0}: select a role").format(row.idx))

	def validate_owner_only_changes(self):
		"""Only the owner and System Manager change scope, shares or the disabled flag."""
		if self.is_new() or self.owner == frappe.session.user or is_system_manager(frappe.session.user):
			return

		before = self.get_doc_before_save()
		if not before:
			return

		if (
			self.scope != before.scope
			or cint(self.disabled) != cint(before.disabled)
			or _share_rows(self) != _share_rows(before)
		):
			frappe.throw(
				_("Only the owner or a System Manager can change scope, sharing or disabled"),
				frappe.PermissionError,
			)

	def validate_title(self):
		owner = self.owner if not self.is_new() else frappe.session.user
		duplicate = frappe.db.exists(
			"Form Preset",
			{
				"owner": owner,
				"target_doctype": self.target_doctype,
				"title": self.title,
				"name": ("!=", self.name),
			},
		)
		if duplicate:
			frappe.throw(_("You already have a preset titled {0} for this DocType").format(self.title))

	def validate_values(self):
		max_bytes = cint(get_settings().max_values_kb) * 1024
		if self.values_json and len(self.values_json.encode()) > max_bytes:
			frappe.throw(
				_("Preset values are larger than the {0} KB limit").format(get_settings().max_values_kb)
			)

		parsed = values.parse(self.values_json)
		if self.is_new() or self.has_value_changed("values_json"):
			fields.validate_values(self.target_doctype, parsed)

		self.values_json = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
		self.field_count = values.count_entries(parsed)

	def validate_user_cap(self):
		if not self.is_new():
			return

		cap = cint(get_settings().max_presets_per_user)
		if frappe.db.count("Form Preset", {"owner": frappe.session.user}) >= cap:
			frappe.throw(_("You can keep at most {0} presets").format(cap))

	def validate_target_permission(self):
		if self.flags.ignore_permissions:
			return

		if self.is_new():
			frappe.has_permission(self.target_doctype, "create", throw=True)
		elif self.has_value_changed("values_json"):
			frappe.has_permission(self.target_doctype, "write", throw=True)


def _share_rows(doc) -> list[tuple]:
	return [(row.share_type, row.user, row.role, cint(row.can_edit)) for row in doc.get("shares") or []]
