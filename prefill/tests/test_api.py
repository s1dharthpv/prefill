import itertools
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, get_first_day, get_last_day, nowdate

from prefill import api, tokens
from prefill.prefill.doctype.form_preset.test_form_preset import make_user
from prefill.tests.utils import CHILD, PARENT, create_test_doctypes, drop_test_doctypes

MARKER = "PREFILL-LOG-MARKER-5512"
_titles = itertools.count(1)


def doc_json(**values) -> dict:
	"""What a form sends: its current doc, new and unsaved."""
	return {"doctype": PARENT, "name": "new-prefill-test-doc-1", "__islocal": 1, "docstatus": 0, **values}


def values_of(fields=None, tables=None) -> str:
	return json.dumps({"version": 1, "fields": fields or {}, "tables": tables or {}})


class TestApi(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_test_doctypes()
		cls.addClassCleanup(cls._drop)

		cls.owner = make_user("api_owner@example.com", ["Desk User"])
		cls.shared = make_user("api_shared@example.com", ["Desk User"])
		cls.other = make_user("api_other@example.com", ["Desk User"])
		cls.sysmgr = make_user("api_sysmgr@example.com", ["Desk User", "System Manager"])

		cls.error_log = frappe.get_doc({"doctype": "Error Log", "error": "x"}).insert(ignore_permissions=True)
		cls.existing = frappe.get_doc({"doctype": PARENT, "title": "Existing"}).insert()

	@classmethod
	def _drop(cls):
		frappe.db.rollback()
		drop_test_doctypes()

	def save(self, owner=None, fields=None, tables=None, **kwargs) -> str:
		data = {"doctype": PARENT, "title": f"Preset {next(_titles)}", "values": values_of(fields, tables)}
		data.update(kwargs)
		with self.set_user(owner or self.owner):
			return api.save_preset(**data)

	def preview(self, preset, doc=None, user=None, **kwargs) -> dict:
		with self.set_user(user or self.owner):
			return api.preview_apply(preset, doc or doc_json(), **kwargs)

	def change(self, result, fieldname) -> dict:
		return next(change for change in result["changes"] if change["fieldname"] == fieldname)

	# capturable fields

	def test_capturable_fields_for_a_plain_user(self):
		with self.set_user(self.owner):
			result = api.get_capturable_fields(PARENT)

		names = {field["fieldname"] for field in result["fields"]}
		self.assertTrue(
			{"title", "status", "due_date", "qty", "flag", "owner_user", "ref_name", "hidden_note"} <= names
		)
		for never in ("secret", "attachment", "picture", "snippet", "locked", "fetched", "restricted"):
			self.assertNotIn(never, names)
		for system in ("name", "owner", "creation", "modified", "docstatus", "idx", "amended_from"):
			self.assertNotIn(system, names)

		tables = {table["fieldname"]: table for table in result["tables"]}
		self.assertEqual(set(tables), {"items"})
		self.assertEqual(tables["items"]["child_doctype"], CHILD)
		child_names = {field["fieldname"] for field in tables["items"]["fields"]}
		self.assertEqual(child_names, {"item_code", "qty", "rate", "link_user", "ref_type", "ref_name"})

	def test_capturable_fields_follow_permlevel(self):
		with self.set_user(self.sysmgr):
			result = api.get_capturable_fields(PARENT)

		self.assertIn("restricted", {field["fieldname"] for field in result["fields"]})
		self.assertIn("restricted_items", {table["fieldname"] for table in result["tables"]})

	def test_capturable_fields_refuses_excluded_and_unreadable_doctypes(self):
		with self.set_user(self.owner):
			for doctype in ("User", "Form Preset", "System Settings", "Has Role"):
				with self.subTest(doctype), self.assertRaises(frappe.ValidationError):
					api.get_capturable_fields(doctype)

			with self.assertRaises(frappe.PermissionError):
				api.get_capturable_fields("Error Log")

	def test_everything_is_refused_when_presets_are_off(self):
		preset = self.save(fields={"title": "a"})
		with self.change_settings("Form Presets Settings", enabled=0), self.set_user(self.owner):
			self.assertEqual(api.list_presets(PARENT), [])
			for call in (
				lambda: api.get_capturable_fields(PARENT),
				lambda: api.preview_apply(preset, doc_json()),
				lambda: api.record_use(preset),
				lambda: api.save_preset(PARENT, "x", values_of({"title": "a"})),
			):
				with self.assertRaises(frappe.ValidationError):
					call()

	# save_preset

	def test_save_preset_validates_against_the_target(self):
		bad = {
			"password field": {"secret": "x"},
			"attach field": {"attachment": "/files/x.png"},
			"read only field": {"locked": "x"},
			"fetch_from field": {"fetched": "x"},
			"code field": {"snippet": "x"},
			"system field": {"name": "x"},
			"unknown field": {"nope": "x"},
			"permlevel field": {"restricted": "x"},
			"token on wrong type": {"title": {"$dyn": "today"}},
			"now on a date": {"due_date": {"$dyn": "now"}},
			"me on a number": {"qty": {"$dyn": "me"}},
			"company on a user link": {"owner_user": {"$dyn": "default_company"}},
		}
		for label, fields in bad.items():
			with self.subTest(label), self.assertRaises(frappe.ValidationError):
				self.save(fields=fields)

	def test_save_preset_rejects_bad_table_content(self):
		bad = {
			"password cell": {"items": [{"secret": "x"}]},
			"fetch_from cell": {"items": [{"fetched": "x"}]},
			"read only cell": {"items": [{"locked": "x"}]},
			"permlevel table": {"restricted_items": [{"item_code": "x"}]},
			"unknown table": {"nope": [{"item_code": "x"}]},
			"token on wrong type": {"items": [{"item_code": {"$dyn": "today"}}]},
		}
		for label, tables in bad.items():
			with self.subTest(label), self.assertRaises(frappe.ValidationError):
				self.save(tables=tables)

	def test_save_preset_accepts_valid_tokens(self):
		name = self.save(
			fields={
				"due_date": {"$dyn": "today", "days": 30},
				"start_at": {"$dyn": "now"},
				"owner_user": {"$dyn": "me"},
				"title": {"$dyn": "me"},
			},
			tables={"items": [{"link_user": {"$dyn": "me"}, "item_code": "A"}]},
		)
		self.assertEqual(frappe.db.get_value("Form Preset", name, "field_count"), 5)

	def test_save_preset_updates_and_checks_the_target(self):
		name = self.save(fields={"title": "a"})
		with self.set_user(self.owner):
			api.save_preset(PARENT, "Renamed", values_of({"title": "b"}), name=name, description="d")
			with self.assertRaises(frappe.ValidationError):
				api.save_preset("ToDo", "Renamed", values_of({"description": "b"}), name=name)

		doc = frappe.get_doc("Form Preset", name)
		self.assertEqual((doc.title, doc.description), ("Renamed", "d"))

	def test_failed_saves_leave_no_values_in_logs(self):
		secret_values = {"secret": MARKER, "locked": MARKER}
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.save(fields=secret_values)

		self.assertNotIn(MARKER, str(ctx.exception))
		self.assertFalse(frappe.db.exists("Error Log", {"error": ["like", f"%{MARKER}%"]}))
		self.assertFalse(frappe.db.exists("Activity Log", {"subject": ["like", f"%{MARKER}%"]}))

	def test_saves_are_not_versioned(self):
		name = self.save(fields={"title": MARKER})
		with self.set_user(self.owner):
			api.save_preset(PARENT, "Again", values_of({"title": MARKER}), name=name)

		self.assertEqual(frappe.db.count("Version", {"ref_doctype": "Form Preset", "docname": name}), 0)

	# list_presets

	def test_list_presets(self):
		mine = self.save(fields={"title": "a"})
		off = self.save(fields={"title": "a"}, owner=self.owner)
		frappe.db.set_value("Form Preset", off, "disabled", 1)
		shared = self.save(
			owner=self.sysmgr,
			fields={"title": "a"},
			scope="Shared",
			shares=[{"share_type": "User", "user": self.shared, "can_edit": 1}],
		)

		with self.set_user(self.owner):
			names = {row.name for row in api.list_presets(PARENT)}
		self.assertIn(mine, names)
		self.assertNotIn(off, names)
		self.assertNotIn(shared, names)

		with self.set_user(self.shared):
			rows = {row.name: row for row in api.list_presets(PARENT)}
		self.assertEqual(set(rows), {shared})
		self.assertTrue(rows[shared].can_edit)

		with self.set_user(self.other):
			self.assertEqual(api.list_presets(PARENT), [])
			self.assertEqual(api.list_presets("Error Log"), [])
			self.assertEqual(api.list_presets("User"), [])

	# preview_apply

	def test_fill_empty_keeps_existing_values_and_overwrite_replaces_them(self):
		preset = self.save(fields={"title": "Preset title", "status": "Open", "priority": "High"})
		doc = doc_json(title="Typed by user", status="Draft", priority="")

		fill = self.preview(preset, doc)
		self.assertEqual(self.change(fill, "title")["action"], "skip")
		self.assertEqual(self.change(fill, "status")["action"], "skip")  # default Draft is a value
		self.assertEqual(self.change(fill, "priority")["action"], "set")
		self.assertEqual(self.change(fill, "priority")["new"], "High")

		overwrite = self.preview(preset, doc, mode="overwrite")
		self.assertEqual(self.change(overwrite, "title")["new"], "Preset title")
		self.assertEqual([change["action"] for change in overwrite["changes"]], ["set", "set", "set"])

	def test_same_value_is_not_a_change(self):
		preset = self.save(fields={"title": "Same", "qty": 3})
		result = self.preview(preset, doc_json(title="Same", qty=3), mode="overwrite")
		self.assertEqual({change["action"] for change in result["changes"]}, {"skip"})

	def test_numeric_zero_counts_as_empty(self):
		preset = self.save(fields={"qty": 4, "flag": 1})
		result = self.preview(preset, doc_json(qty=0, flag=0))
		self.assertEqual({change["action"] for change in result["changes"]}, {"set"})

	def test_tables_append_and_replace(self):
		preset = self.save(tables={"items": [{"item_code": "A", "qty": 2}, {"item_code": "B", "rate": 1.5}]})
		doc = doc_json(items=[{"item_code": "X"}])

		append = self.preview(preset, doc, table_mode="append")["tables"][0]
		self.assertEqual((append["mode"], append["current_rows"], len(append["rows"])), ("append", 1, 2))
		self.assertEqual(append["rows"][0]["values"], {"item_code": "A", "qty": 2})

		replace = self.preview(preset, doc, table_mode="replace")["tables"][0]
		self.assertEqual(replace["mode"], "replace")

	def test_bad_link_and_select_values_are_skipped_with_a_reason(self):
		preset = self.save(fields={"title": "a"})
		# values that were valid when saved but went stale, written straight to the database
		stale = values_of(
			{"owner_user": "ghost@example.com", "status": "Archived", "priority": "High"},
			{"items": [{"link_user": "ghost@example.com", "item_code": "A"}]},
		)
		frappe.db.set_value("Form Preset", preset, "values_json", stale)

		result = self.preview(preset)
		self.assertEqual(self.change(result, "owner_user")["action"], "skip")
		self.assertTrue(self.change(result, "owner_user")["reason"])
		self.assertEqual(self.change(result, "status")["action"], "skip")
		self.assertEqual(self.change(result, "priority")["action"], "set")

		row = result["tables"][0]["rows"][0]
		self.assertEqual(row["values"], {"item_code": "A"})
		self.assertEqual([cell["fieldname"] for cell in row["skipped"]], ["link_user"])

	def test_row_with_nothing_fillable_is_left_out_with_a_warning(self):
		preset = self.save(fields={"title": "a"})
		stale = values_of({}, {"items": [{"link_user": "ghost@example.com"}]})
		frappe.db.set_value("Form Preset", preset, "values_json", stale)

		result = self.preview(preset)
		self.assertEqual(result["tables"][0]["rows"], [])
		self.assertEqual(len(result["warnings"]), 1)

	def test_dynamic_link_follows_the_link_that_names_its_doctype(self):
		# only users who can read DocType records may fill a Link to DocType, so this runs as a System Manager
		preset = self.save(owner=self.sysmgr, fields={"ref_type": PARENT, "ref_name": self.existing.name})
		result = self.preview(preset, user=self.sysmgr)
		self.assertEqual(self.change(result, "ref_name")["action"], "set")

		# a preset that stores only the name is checked against the DocType the form already has
		only_name = values_of({"ref_name": self.existing.name})
		frappe.db.set_value("Form Preset", preset, "values_json", only_name)
		self.assertEqual(self.change(self.preview(preset, user=self.sysmgr), "ref_name")["action"], "skip")
		with_type = doc_json(ref_type=PARENT)
		self.assertEqual(
			self.change(self.preview(preset, with_type, user=self.sysmgr), "ref_name")["action"], "set"
		)

		# a plain user cannot read the DocType record, so the Link to DocType is skipped, and so is what depends on it
		frappe.db.set_value("Form Preset", preset, "scope", "Everyone")
		with self.change_settings("Form Presets Settings", allow_everyone_scope=1):
			full = values_of({"ref_type": PARENT, "ref_name": self.existing.name})
			frappe.db.set_value("Form Preset", preset, "values_json", full)
			result = self.preview(preset, user=self.owner)
			self.assertEqual(self.change(result, "ref_type")["action"], "skip")
			self.assertEqual(self.change(result, "ref_name")["action"], "skip")

	def test_field_changes_since_saving_are_skipped(self):
		preset = self.save(fields={"title": "a"})
		stale = values_of(
			{"secret": "x", "locked": "x", "fetched": "x", "nope": "x", "restricted": "x", "title": "ok"},
			{"restricted_items": [{"item_code": "A"}], "nope": [{"item_code": "A"}]},
		)
		frappe.db.set_value("Form Preset", preset, "values_json", stale)

		result = self.preview(preset)
		actions = {change["fieldname"]: change["action"] for change in result["changes"]}
		self.assertEqual(actions.pop("title"), "set")
		self.assertEqual(set(actions.values()), {"skip"})
		for change in result["changes"]:
			if change["action"] == "skip":
				self.assertTrue(change["reason"], change["fieldname"])
		for table in result["tables"]:
			self.assertEqual((table["action"], table["rows"]), ("skip", []))
			self.assertTrue(table["reason"])

	def test_unreadable_link_target_is_skipped(self):
		preset = self.save(owner=self.sysmgr, fields={"restricted_link": self.error_log.name})
		frappe.db.set_value("Form Preset", preset, "scope", "Everyone")
		with self.change_settings("Form Presets Settings", allow_everyone_scope=1):
			self.assertEqual(
				self.change(self.preview(preset, user=self.owner), "restricted_link")["action"], "skip"
			)
			self.assertEqual(
				self.change(self.preview(preset, user=self.sysmgr), "restricted_link")["action"], "set"
			)

	def test_permlevel_blocks_filling_for_a_plain_user(self):
		preset = self.save(owner=self.sysmgr, fields={"restricted": "secret"})
		frappe.db.set_value("Form Preset", preset, "scope", "Everyone")
		with self.change_settings("Form Presets Settings", allow_everyone_scope=1):
			self.assertEqual(
				self.change(self.preview(preset, user=self.owner), "restricted")["action"], "skip"
			)
			self.assertEqual(
				self.change(self.preview(preset, user=self.sysmgr), "restricted")["action"], "set"
			)

	def test_dynamic_values_resolve_on_the_server(self):
		preset = self.save(
			fields={
				"due_date": {"$dyn": "today", "days": 30},
				"start_at": {"$dyn": "today"},
				"owner_user": {"$dyn": "me"},
				"title": {"$dyn": "me"},
			}
		)
		result = self.preview(preset)
		self.assertEqual(self.change(result, "due_date")["new"], add_days(nowdate(), 30))
		self.assertEqual(self.change(result, "start_at")["new"], f"{nowdate()} 00:00:00")
		self.assertEqual(self.change(result, "owner_user")["new"], self.owner)
		self.assertEqual(self.change(result, "title")["new"], self.owner)

	def test_preview_never_writes(self):
		preset = self.save(fields={"title": "a"}, tables={"items": [{"item_code": "A"}]})
		before = frappe.db.count(PARENT)
		self.preview(preset, mode="overwrite", table_mode="replace")
		self.assertEqual(frappe.db.count(PARENT), before)

	def test_submitted_documents_are_refused(self):
		preset = self.save(fields={"title": "a"})

		# the client says it is submitted
		with self.assertRaises(frappe.ValidationError):
			self.preview(preset, doc_json(docstatus=1))

		# the client lies, the stored document is submitted
		submitted = frappe.get_doc({"doctype": PARENT, "title": "Done"}).insert()
		submitted.submit()
		with self.assertRaises(frappe.ValidationError):
			self.preview(preset, doc_json(name=submitted.name, docstatus=0))

		# a stored draft is fine
		self.preview(preset, doc_json(name=self.existing.name))

	def test_preview_needs_permission_on_preset_and_target(self):
		preset = self.save(fields={"title": "a"})
		with self.assertRaises(frappe.PermissionError):
			self.preview(preset, user=self.other)

		with self.change_settings("Form Presets Settings", allow_everyone_scope=1):
			frappe.db.set_value("Form Preset", preset, "scope", "Everyone")
			self.preview(preset, user=self.other)  # usable by everyone

	def test_preview_checks_its_arguments(self):
		preset = self.save(fields={"title": "a"})
		disabled = self.save(fields={"title": "a"})
		frappe.db.set_value("Form Preset", disabled, "disabled", 1)

		for label, call in {
			"unknown mode": lambda: self.preview(preset, mode="merge"),
			"unknown table mode": lambda: self.preview(preset, table_mode="merge"),
			"wrong doctype": lambda: self.preview(preset, {"doctype": "ToDo"}),
			"not an object": lambda: self.preview(preset, "[1]"),
			"disabled preset": lambda: self.preview(disabled),
		}.items():
			with self.subTest(label), self.assertRaises(frappe.ValidationError):
				call()

	def test_preview_accepts_a_json_string(self):
		preset = self.save(fields={"title": "a"})
		result = self.preview(preset, json.dumps(doc_json()))
		self.assertEqual(self.change(result, "title")["action"], "set")

	# record_use, delete_preset

	def test_record_use_counts_for_anyone_who_may_use_the_preset(self):
		preset = self.save(
			fields={"title": "a"},
			scope="Shared",
			shares=[{"share_type": "User", "user": self.shared, "can_edit": 0}],
		)
		for _ in range(2):
			with self.set_user(self.shared):
				api.record_use(preset)

		count, last_used = frappe.db.get_value("Form Preset", preset, ["use_count", "last_used"])
		self.assertEqual(count, 2)
		self.assertTrue(last_used)

		with self.set_user(self.other), self.assertRaises(frappe.PermissionError):
			api.record_use(preset)

	def test_delete_preset(self):
		preset = self.save(
			fields={"title": "a"},
			scope="Shared",
			shares=[{"share_type": "User", "user": self.shared, "can_edit": 1}],
		)
		with self.set_user(self.shared), self.assertRaises(frappe.PermissionError):
			api.delete_preset(preset)

		with self.set_user(self.owner):
			api.delete_preset(preset)
		self.assertFalse(frappe.db.exists("Form Preset", preset))

	# malformed input

	def test_malformed_arguments_are_validation_errors(self):
		preset = self.save(fields={"title": "a"})
		deep = "[" * 50000
		bad = {
			"shares not json": lambda: api.save_preset(
				PARENT, "x", values_of({"title": "a"}), shares="{oops"
			),
			"shares too deep": lambda: api.save_preset(PARENT, "x", values_of({"title": "a"}), shares=deep),
			"shares a number": lambda: api.save_preset(PARENT, "x", values_of({"title": "a"}), shares=5),
			"shares rows not objects": lambda: api.save_preset(
				PARENT, "x", values_of({"title": "a"}), shares=[1]
			),
			"values not an object": lambda: api.save_preset(PARENT, "x", "[1]"),
			"values too deep": lambda: api.save_preset(PARENT, "x", deep),
			"doc not json": lambda: api.preview_apply(preset, "{oops"),
			"doc too deep": lambda: api.preview_apply(preset, deep),
			"doc a list": lambda: api.preview_apply(preset, [1]),
			"preset a list": lambda: api.preview_apply([preset], doc_json()),
		}
		# A wrong argument type is stopped by Frappe's own type check (FrappeTypeError). Both it and
		# ValidationError answer HTTP 417, and Frappe only copies the request into the Error Log for 500 and up.
		refusals = (frappe.ValidationError, frappe.exceptions.FrappeTypeError)
		with self.set_user(self.owner):
			for label, call in bad.items():
				with self.subTest(label), self.assertRaises(refusals) as ctx:
					call()
				self.assertLess(ctx.exception.http_status_code, 500)

	def test_odd_values_in_the_posted_form_do_not_crash_the_preview(self):
		preset = self.save(fields={"title": "a", "qty": 3}, tables={"items": [{"item_code": "A"}]})
		odd = {
			"table is a number": {"items": 5},
			"table is text": {"items": "x"},
			"table is an object": {"items": {"a": 1}},
			"field is a list": {"title": [1], "qty": [2]},
			"field is an object": {"title": {"a": 1}, "qty": {"a": 1}},
			"name is a list": {"name": ["x"]},
			"docstatus is a list": {"docstatus": [1]},
		}
		for label, extra in odd.items():
			with self.subTest(label):
				try:
					result = self.preview(preset, doc_json(**extra))
				except frappe.ValidationError:
					continue  # a clean refusal is fine
				self.assertIn("changes", result)

	# transport

	def test_writes_and_diffs_are_post_only(self):
		for function in (api.save_preset, api.preview_apply, api.record_use, api.delete_preset):
			with self.subTest(function.__name__):
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[function], ["POST"])


class TestTokens(IntegrationTestCase):
	def df(self, fieldtype):
		return frappe._dict(fieldtype=fieldtype)

	def test_date_tokens(self):
		self.assertEqual(tokens.resolve({"$dyn": "today"}, self.df("Date")), (nowdate(), None))
		self.assertEqual(
			tokens.resolve({"$dyn": "today", "days": -3}, self.df("Date"))[0], add_days(nowdate(), -3)
		)
		self.assertEqual(
			tokens.resolve({"$dyn": "month_start"}, self.df("Date"))[0], str(get_first_day(nowdate()))
		)
		self.assertEqual(
			tokens.resolve({"$dyn": "month_end"}, self.df("Date"))[0], str(get_last_day(nowdate()))
		)

	def test_now_and_me(self):
		value, reason = tokens.resolve({"$dyn": "now"}, self.df("Datetime"))
		self.assertIsNone(reason)
		self.assertRegex(value, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
		self.assertEqual(tokens.resolve({"$dyn": "me"}, self.df("Link")), (frappe.session.user, None))

	def test_default_company_without_a_company_doctype_gives_a_reason(self):
		value, reason = tokens.resolve({"$dyn": "default_company"}, self.df("Link"))
		self.assertIsNone(value)
		self.assertTrue(reason)

	def test_default_company(self):
		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.defaults.get_user_default", return_value="Acme Ltd"),
		):
			self.assertEqual(tokens.resolve({"$dyn": "default_company"}, self.df("Link")), ("Acme Ltd", None))

		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.defaults.get_user_default", return_value=None),
			patch("frappe.db.get_single_value", return_value=None),
		):
			value, reason = tokens.resolve({"$dyn": "default_company"}, self.df("Link"))
			self.assertIsNone(value)
			self.assertTrue(reason)
