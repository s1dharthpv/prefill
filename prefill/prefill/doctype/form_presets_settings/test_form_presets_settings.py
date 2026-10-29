import frappe
from frappe.tests import IntegrationTestCase

from prefill.boot import boot_session


def clear_exclusions():
	settings = frappe.get_doc("Form Presets Settings")
	settings.set("excluded_doctypes", [])
	settings.save()


class TestFormPresetsSettings(IntegrationTestCase):
	def test_defaults(self):
		settings = frappe.get_doc("Form Presets Settings")
		self.assertEqual(
			(
				settings.enabled,
				settings.allow_everyone_scope,
				settings.max_presets_per_user,
				settings.max_values_kb,
			),
			(1, 0, 200, 64),
		)

	def test_limits_are_validated(self):
		for field, value in (("max_presets_per_user", 0), ("max_values_kb", 0), ("max_values_kb", 1025)):
			with self.subTest(field=field, value=value):
				settings = frappe.get_doc("Form Presets Settings")
				settings.set(field, value)
				with self.assertRaises(frappe.ValidationError):
					settings.save()

	def test_duplicate_exclusions_rejected(self):
		settings = frappe.get_doc("Form Presets Settings")
		settings.extend("excluded_doctypes", [{"excluded_doctype": "Note"}, {"excluded_doctype": "Note"}])
		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_only_system_manager_can_open_settings(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "fp_settings@example.com",
				"first_name": "fp_settings",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles("Desk User")
		self.assertFalse(frappe.has_permission("Form Presets Settings", "read", user=user.name))
		self.assertTrue(frappe.has_permission("Form Presets Settings", "write", user="Administrator"))

	def test_boot_flag(self):
		info = frappe._dict()
		boot_session(info)
		self.assertEqual(info.form_presets["enabled"], 1)
		for name in ("User", "Role", "Form Preset", "DocType"):
			self.assertIn(name, info.form_presets["excluded"])

	def test_boot_flag_follows_settings(self):
		settings = frappe.get_doc("Form Presets Settings")
		settings.append("excluded_doctypes", {"excluded_doctype": "Note"})
		settings.save()
		self.addCleanup(clear_exclusions)

		with self.change_settings("Form Presets Settings", enabled=0):
			info = frappe._dict()
			boot_session(info)
			self.assertEqual(info.form_presets["enabled"], 0)
			self.assertIn("Note", info.form_presets["excluded"])
