import json

import frappe
from frappe.tests import IntegrationTestCase

from prefill import values


def doc(fields=None, tables=None, **extra) -> str:
	return json.dumps({"version": 1, "fields": fields or {}, "tables": tables or {}, **extra})


class TestValues(IntegrationTestCase):
	def test_valid_values_parse(self):
		parsed = values.parse(
			doc(
				{"customer": "ACME", "qty": 2, "rate": 1.5, "flag": True, "posting_date": {"$dyn": "today"}},
				{"items": [{"item_code": "SKU-1", "date": {"$dyn": "today", "days": -7}}]},
			)
		)
		self.assertEqual(values.count_entries(parsed), 6)

	def test_missing_sections_default_to_empty(self):
		parsed = values.parse('{"version":1,"fields":{"a":"b"}}')
		self.assertEqual(parsed["tables"], {})

	def test_bad_documents_are_rejected(self):
		bad = {
			"empty string": "",
			"not json": "{oops",
			"not an object": "[1]",
			"wrong version": '{"version":2,"fields":{"a":1}}',
			"missing version": '{"fields":{"a":1}}',
			"extra top level key": doc({"a": 1}, extra=1),
			"fields not object": '{"version":1,"fields":[1]}',
			"rows not list": doc({}, {"items": {"a": 1}}),
			"row not object": doc({}, {"items": ["x"]}),
			"nothing in it": doc(),
			"only empty tables": doc({}, {"items": []}),
			"deep nesting": "[" * 50000,
		}
		for label, raw in bad.items():
			with self.subTest(label), self.assertRaises(frappe.ValidationError):
				values.parse(raw)

	def test_reserved_keys_are_rejected(self):
		for key in (
			"name",
			"idx",
			"owner",
			"creation",
			"modified",
			"docstatus",
			"doctype",
			"parent",
			"parenttype",
		):
			with self.subTest(key=key):
				with self.assertRaises(frappe.ValidationError):
					values.parse(doc({key: "x"}))
				with self.assertRaises(frappe.ValidationError):
					values.parse(doc({}, {"items": [{key: "x"}]}))

	def test_non_scalar_values_are_rejected(self):
		for value in (None, [1], {"a": 1}):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				values.parse(doc({"a": value}))

	def test_tokens(self):
		for token in values.TOKENS:
			values.parse(doc({"a": {"$dyn": token}}))

		bad = [
			{"$dyn": "tomorrow"},
			{"$dyn": "now", "days": 1},
			{"$dyn": "today", "days": 3651},
			{"$dyn": "today", "days": -3651},
			{"$dyn": "today", "days": 1.5},
			{"$dyn": "today", "days": True},
			{"$dyn": "today", "days": "3"},
			{"$dyn": "today", "other": 1},
			{"days": 1},
		]
		for token in bad:
			with self.subTest(token=token), self.assertRaises(frappe.ValidationError):
				values.parse(doc({"a": token}))

		values.parse(doc({"a": {"$dyn": "today", "days": 3650}}))
		values.parse(doc({"a": {"$dyn": "today", "days": -3650}}))

	def test_error_messages_do_not_echo_values(self):
		secret = "S3CRET-VALUE-123"
		with self.assertRaises(frappe.ValidationError) as ctx:
			values.parse(doc({"name": secret}))
		self.assertNotIn(secret, str(ctx.exception))
