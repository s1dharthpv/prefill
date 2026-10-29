import itertools

import frappe
from frappe.tests import IntegrationTestCase

VALUES = '{"version":1,"fields":{"description":"x","priority":"High"},"tables":{}}'
VALUES_BY_TARGET = {
	"Error Log": '{"version":1,"fields":{"seen":1},"tables":{}}',
	"Note": '{"version":1,"fields":{"title":"x"},"tables":{}}',
}
MARKER = "PREFILL-MARKER-7391"
ROLE = "Accounts User"

_titles = itertools.count(1)


def make_user(email: str, roles: list[str]):
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
	).insert(ignore_permissions=True)
	user.add_roles(*roles)
	return user.name


def clear_exclusions():
	settings = frappe.get_doc("Form Presets Settings")
	settings.set("excluded_doctypes", [])
	settings.save()


class TestFormPreset(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.owner = make_user("fp_owner@example.com", ["Desk User"])
		cls.shared = make_user("fp_shared@example.com", ["Desk User"])
		cls.editor = make_user("fp_editor@example.com", ["Desk User"])
		cls.role_user = make_user("fp_role@example.com", ["Desk User", ROLE])
		cls.other = make_user("fp_other@example.com", ["Desk User"])
		cls.sysmgr = make_user("fp_sysmgr@example.com", ["Desk User", "System Manager"])

	def make_preset(self, owner=None, **kwargs) -> "frappe.model.document.Document":
		data = {
			"doctype": "Form Preset",
			"title": f"Preset {next(_titles)}",
			"target_doctype": "ToDo",
		}
		data.update(kwargs)
		data.setdefault("values_json", VALUES_BY_TARGET.get(data["target_doctype"], VALUES))
		with self.set_user(owner or self.owner):
			return frappe.get_doc(data).insert()

	def make_shared_preset(self, **kwargs):
		return self.make_preset(
			scope="Shared",
			shares=[
				{"share_type": "User", "user": self.shared, "can_edit": 0},
				{"share_type": "User", "user": self.editor, "can_edit": 1},
				{"share_type": "Role", "role": ROLE, "can_edit": 0},
			],
			**kwargs,
		)

	def can(self, user, ptype, preset) -> bool:
		return bool(frappe.has_permission("Form Preset", ptype, doc=preset.name, user=user))

	def listed(self, user) -> set[str]:
		with self.set_user(user):
			return set(frappe.get_list("Form Preset", pluck="name", limit_page_length=0))

	def assert_matrix(self, preset, expected: dict):
		for user, (read, write, delete) in expected.items():
			with self.subTest(user=user):
				self.assertEqual(self.can(user, "read", preset), read, "read")
				self.assertEqual(self.can(user, "write", preset), write, "write")
				self.assertEqual(self.can(user, "delete", preset), delete, "delete")
				self.assertEqual(preset.name in self.listed(user), read, "list")

	def test_shared_matrix(self):
		preset = self.make_shared_preset()
		self.assert_matrix(
			preset,
			{
				self.owner: (True, True, True),
				self.shared: (True, False, False),
				self.editor: (True, True, False),
				self.role_user: (True, False, False),
				self.other: (False, False, False),
				self.sysmgr: (True, True, True),
				"Administrator": (True, True, True),
			},
		)

	def test_private_matrix(self):
		preset = self.make_preset()
		self.assert_matrix(
			preset,
			{
				self.owner: (True, True, True),
				self.shared: (False, False, False),
				self.other: (False, False, False),
				self.sysmgr: (True, True, True),
			},
		)

	def test_everyone_matrix_follows_setting(self):
		with self.change_settings("Form Presets Settings", allow_everyone_scope=1):
			preset = self.make_preset(scope="Everyone")
			self.assert_matrix(
				preset,
				{
					self.owner: (True, True, True),
					self.other: (True, False, False),
					self.sysmgr: (True, True, True),
				},
			)

		# setting turned off again: the existing preset is no longer usable by others
		self.assert_matrix(
			preset,
			{
				self.owner: (True, True, True),
				self.other: (False, False, False),
			},
		)

	def test_owner_can_still_edit_an_everyone_preset_after_the_setting_is_turned_off(self):
		with self.change_settings("Form Presets Settings", allow_everyone_scope=1):
			preset = self.make_preset(scope="Everyone")

		with self.set_user(self.owner):
			doc = frappe.get_doc("Form Preset", preset.name)
			doc.title = "Renamed while Everyone is off"
			doc.save()

			# but choosing Everyone again is still refused
			private = self.make_preset()
			private.scope = "Everyone"
			with self.assertRaises(frappe.ValidationError):
				private.save()

	def test_everyone_scope_rejected_when_setting_off(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_preset(scope="Everyone")

	def test_unreadable_target_hides_preset(self):
		# Error Log is readable by System Manager only
		preset = self.make_preset(
			owner=self.sysmgr,
			target_doctype="Error Log",
			scope="Shared",
			shares=[{"share_type": "User", "user": self.other}],
		)
		self.assert_matrix(
			preset,
			{
				self.other: (False, False, False),
				self.sysmgr: (True, True, True),
			},
		)

	def test_create_needs_create_on_target(self):
		with self.assertRaises(frappe.PermissionError):
			self.make_preset(owner=self.other, target_doctype="Error Log")

	def test_editor_edits_values_but_not_scope_or_sharing(self):
		preset = self.make_shared_preset()
		with self.set_user(self.editor):
			doc = frappe.get_doc("Form Preset", preset.name)
			doc.title = "Renamed by editor"
			doc.save()

			doc.scope = "Private"
			with self.assertRaises(frappe.PermissionError):
				doc.save()

			doc = frappe.get_doc("Form Preset", preset.name)
			doc.append("shares", {"share_type": "User", "user": self.other})
			with self.assertRaises(frappe.PermissionError):
				doc.save()

			doc = frappe.get_doc("Form Preset", preset.name)
			doc.disabled = 1
			with self.assertRaises(frappe.PermissionError):
				doc.save()

	def test_only_owner_deletes(self):
		preset = self.make_shared_preset()
		for user in (self.shared, self.editor, self.role_user):
			with self.subTest(user=user), self.set_user(user), self.assertRaises(frappe.PermissionError):
				frappe.delete_doc("Form Preset", preset.name)

		with self.set_user(self.owner):
			frappe.delete_doc("Form Preset", preset.name)
		self.assertFalse(frappe.db.exists("Form Preset", preset.name))

	def test_delete_keeps_values_out_of_deleted_document(self):
		preset = self.make_preset(
			values_json=f'{{"version":1,"fields":{{"description":"{MARKER}"}},"tables":{{}}}}'
		)
		with self.set_user(self.owner):
			frappe.delete_doc("Form Preset", preset.name)

		data = frappe.db.get_value(
			"Deleted Document", {"deleted_doctype": "Form Preset", "deleted_name": preset.name}, "data"
		)
		self.assertTrue(data, "expected a Deleted Document row")
		self.assertNotIn(MARKER, data)

	def test_values_not_versioned(self):
		self.assertFalse(frappe.get_meta("Form Preset").track_changes)

	def test_title_is_unique_per_owner_and_target(self):
		self.make_preset(title="Weekly invoice")
		with self.assertRaises(frappe.ValidationError):
			self.make_preset(title="Weekly invoice")

		# other owner, or other target, is fine
		self.make_preset(owner=self.other, title="Weekly invoice")
		self.make_preset(title="Weekly invoice", target_doctype="Note")

	def test_per_user_cap(self):
		capped = make_user("fp_capped@example.com", ["Desk User"])
		with self.change_settings("Form Presets Settings", max_presets_per_user=1):
			self.make_preset(owner=capped)
			with self.assertRaises(frappe.ValidationError):
				self.make_preset(owner=capped)

	def test_values_size_cap(self):
		padding = "a" * 2048
		big = f'{{"version":1,"fields":{{"description":"{padding}"}},"tables":{{}}}}'
		with self.change_settings("Form Presets Settings", max_values_kb=1):
			with self.assertRaises(frappe.ValidationError):
				self.make_preset(values_json=big)

		self.make_preset(values_json=big)  # fine under the default cap

	def test_excluded_targets(self):
		for target in ("User", "Form Preset", "System Settings", "Has Role", "DocType"):
			with self.subTest(target=target), self.assertRaises(frappe.ValidationError):
				self.make_preset(owner="Administrator", target_doctype=target)

	def test_configured_exclusion(self):
		settings = frappe.get_doc("Form Presets Settings")
		settings.append("excluded_doctypes", {"excluded_doctype": "Note"})
		settings.save()
		self.addCleanup(clear_exclusions)

		with self.assertRaises(frappe.ValidationError):
			self.make_preset(target_doctype="Note")

	def test_shares_are_dropped_unless_shared(self):
		preset = self.make_preset(scope="Private", shares=[{"share_type": "User", "user": self.shared}])
		self.assertEqual(len(preset.shares), 0)

	def test_shared_needs_rows(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_preset(scope="Shared")

		with self.assertRaises(frappe.ValidationError):
			self.make_preset(scope="Shared", shares=[{"share_type": "Role"}])

	def test_target_is_set_once(self):
		preset = self.make_preset()
		preset.target_doctype = "Note"
		with self.assertRaises(frappe.CannotChangeConstantError):
			preset.save()

	def test_field_count_is_computed(self):
		self.assertEqual(self.make_preset().field_count, 2)
