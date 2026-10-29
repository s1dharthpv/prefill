"""UI smoke test: save a preset on a form with a child table, apply it to a new form, review the diff, save.

Runs against a dev site in a real browser. It is not part of `bench run-tests` and the app does not
depend on it. Setup, from the bench:

    bench --site <site> execute prefill.tests.utils.create_test_doctypes
    pip install playwright && playwright install chromium    # in any environment you like
    PREFILL_UI_PASSWORD=... python ui_tests/smoke.py --url http://<site>:8000
    bench --site <site> execute prefill.tests.utils.drop_test_doctypes

Options: --user (default Administrator), --headed, --record-dir DIR (saves a video of the run), --slow MS,
--browser-path (use an installed Chromium instead of the one `playwright install` fetches).
The password is read from PREFILL_UI_PASSWORD and never has a default.
"""

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

DOCTYPE = "Prefill Test Doc"
ROUTE = "prefill-test-doc"
TITLE = "UI smoke preset"
IGNORED_ERRORS = ("socket.io", "Failed to load resource")  # no realtime server on a plain `bench serve`


def step(message: str):
	print(f"- {message}", flush=True)


def check(condition, message: str):
	if not condition:
		raise AssertionError(message)


def login(page, base: str, user: str, password: str):
	page.goto(f"{base}/login")
	page.fill("#login_email", user)
	page.fill("#login_password", password)
	page.get_by_role("button", name="Continue").first.click()
	page.wait_for_url("**/desk**", wait_until="commit", timeout=60000)


def open_form(page, base: str, route: str):
	page.goto(f"{base}/desk/{route}", wait_until="commit")
	page.wait_for_selector(".form-layout", timeout=60000)
	page.wait_for_timeout(1500)


def click_menu_item(page, text: str):
	page.evaluate(
		"""(text) => [...document.querySelectorAll("a.dropdown-item")]
			.find((a) => a.innerText.trim() === text).click()""",
		text,
	)


def toolbar_labels(page) -> list[str]:
	return page.evaluate(
		"""() => [...document.querySelectorAll(".page-head button, .page-head a.dropdown-item")]
			.map((el) => el.innerText.trim())"""
	)


def has_presets_ui(page) -> dict:
	labels = toolbar_labels(page)
	return {
		"button": "Presets" in labels or any(label.startswith("Presets >") for label in labels),
		"menu": "Save as Preset" in labels,
	}


def call(page, method: str, **args):
	return page.evaluate("([m, a]) => frappe.xcall(m, a)", [method, args])


def run(page, base: str, pause):
	step("open a new form and check the Presets UI is there")
	open_form(page, base, f"{ROUTE}/new")
	for old in call(page, "prefill.api.list_presets", doctype=DOCTYPE):
		if old["title"] == TITLE:
			call(page, "prefill.api.delete_preset", name=old["name"])
	ui = has_presets_ui(page)
	check(ui["button"] and ui["menu"], f"Presets button or menu item missing: {ui}")

	step("fill the form, including child table rows")
	page.evaluate(
		"""async () => {
			const frm = cur_frm;
			await frm.set_value("title", "Weekly invoice");
			await frm.set_value("priority", "High");
			await frm.set_value("qty", 5);
			await frm.set_value("due_date", "2026-11-15");
			frm.add_child("items", { item_code: "SKU-1", qty: 2, rate: 10 });
			frm.add_child("items", { item_code: "SKU-2", qty: 1, rate: 99.5 });
			frm.refresh_field("items");
		}"""
	)
	pause()

	step("Save as Preset")
	click_menu_item(page, "Save as Preset")
	page.wait_for_selector(".modal.show .modal-title")
	page.wait_for_timeout(1200)
	picked = page.evaluate("() => cur_dialog.get_value('picked_fields')")
	tables = page.evaluate("() => cur_dialog.get_value('picked_tables')")
	check(
		"title" in picked and "qty" in picked and "due_date" in picked,
		f"filled fields not pre-ticked: {picked}",
	)
	check("flag" not in picked, "an unchecked Check must not be pre-ticked")
	check(tables == ["items"], f"expected the filled child table pre-ticked, got {tables}")
	pause()
	page.fill(".modal.show input[data-fieldname='title']", TITLE)
	page.press(".modal.show input[data-fieldname='title']", "Tab")
	page.locator(".modal.show").get_by_role("button", name="Save").click()
	page.wait_for_selector(".modal.show", state="detached")
	page.wait_for_timeout(1000)

	presets = call(page, "prefill.api.list_presets", doctype=DOCTYPE)
	saved_as = [p["name"] for p in presets if p["title"] == TITLE]
	check(len(saved_as) == 1, f"preset was not saved: {presets}")
	preset = saved_as[0]

	try:
		step("reload to a new form that already has a typed title and one old row")
		open_form(page, base, f"{ROUTE}/new")
		page.evaluate(
			"""async () => {
				await cur_frm.set_value("title", "Typed by hand");
				cur_frm.add_child("items", { item_code: "OLD", qty: 9 });
				cur_frm.refresh_field("items");
			}"""
		)
		click_menu_item(page, "Apply a Preset")
		page.wait_for_selector(".modal.show .list-group-item")
		check(
			TITLE in page.locator(".modal.show .list-group").inner_text(), "preset not listed in the chooser"
		)
		pause()
		page.locator(".modal.show .list-group-item").first.click()
		page.wait_for_selector(".modal.show table")
		page.wait_for_timeout(1200)
		check(page.locator(".modal.show").count() == 1, "an error dialog opened over the diff")

		step("diff: fill empty keeps typed values, skipped rows say why")
		diff = page.locator(".modal.show table").inner_text()
		check("Already has a value" in diff, "typed Title should be skipped with a reason")
		check("added after 1 existing rows" in diff, "append mode should say rows are added")
		pause()

		step("diff: overwrite and replace change the preview")
		page.select_option(".modal.show select[data-fieldname='mode']", "overwrite")
		page.wait_for_timeout(1200)
		page.select_option(".modal.show select[data-fieldname='table_mode']", "replace")
		page.wait_for_timeout(1200)
		diff = page.locator(".modal.show table").inner_text()
		check("Weekly invoice" in diff, "overwrite should offer the preset title")
		check("replaces 1 existing rows" in diff, "replace mode should say rows are replaced")
		pause()

		step("apply, then check the form and that nothing is saved yet")
		page.locator(".modal.show").get_by_role("button", name="Apply").click()
		page.wait_for_timeout(2000)
		form = page.evaluate(
			"""() => ({
				title: cur_frm.doc.title, qty: cur_frm.doc.qty, priority: cur_frm.doc.priority,
				due: cur_frm.doc.due_date, items: cur_frm.doc.items.map((r) => r.item_code),
				dirty: cur_frm.is_dirty(), local: Boolean(cur_frm.doc.__islocal),
			})"""
		)
		check(form["title"] == "Weekly invoice" and form["qty"] == 5, f"values not applied: {form}")
		check(form["items"] == ["SKU-1", "SKU-2"], f"rows not replaced: {form}")
		check(form["dirty"] and form["local"], f"applying must leave the form unsaved: {form}")
		pause()

		step("normal save runs, and the use is counted")
		page.keyboard.press("Control+s")
		page.wait_for_timeout(2500)
		check(page.evaluate("() => !cur_frm.doc.__islocal && !cur_frm.is_dirty()"), "form did not save")
		count = call(
			page,
			"frappe.client.get_value",
			doctype="Form Preset",
			filters={"name": preset},
			fieldname="use_count",
		)
		check(count["use_count"] == 1, f"use_count should be 1: {count}")

		step("a submitted document gets no Presets button")
		doc = call(page, "frappe.client.insert", doc={"doctype": DOCTYPE, "title": "Locked"})
		call(page, "frappe.client.submit", doc=doc)
		open_form(page, base, f"{ROUTE}/{doc['name']}")
		ui = has_presets_ui(page)
		check(not ui["button"], f"Presets button must not show on a submitted document: {ui}")

		step("an excluded DocType (User) gets no Presets UI")
		open_form(page, base, "user/Administrator")
		ui = has_presets_ui(page)
		check(not ui["button"] and not ui["menu"], f"excluded DocType should have no Presets UI: {ui}")
	finally:
		step("clean up")
		call(page, "prefill.api.delete_preset", name=preset)
		for row in call(
			page, "frappe.client.get_list", doctype=DOCTYPE, fields=["name", "docstatus"], limit_page_length=0
		):
			if row["docstatus"] == 1:
				call(page, "frappe.client.cancel", doctype=DOCTYPE, name=row["name"])
			call(page, "frappe.client.delete", doctype=DOCTYPE, name=row["name"])


def main() -> int:
	parser = argparse.ArgumentParser(
		description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
	)
	parser.add_argument("--url", required=True, help="site URL, e.g. http://mysite.localhost:8000")
	parser.add_argument("--user", default="Administrator")
	parser.add_argument("--headed", action="store_true")
	parser.add_argument("--browser-path", help="path to a Chromium or Chrome executable")
	parser.add_argument("--record-dir", help="save a video of the run here")
	parser.add_argument("--slow", type=int, default=0, help="slow every browser action down by this many ms")
	parser.add_argument(
		"--hold", type=int, default=0, help="pause this many ms at key moments (for recordings)"
	)
	args = parser.parse_args()

	password = os.environ.get("PREFILL_UI_PASSWORD")
	if not password:
		print("Set PREFILL_UI_PASSWORD.", file=sys.stderr)
		return 2

	errors = []
	with sync_playwright() as p:
		browser = p.chromium.launch(
			headless=not args.headed, slow_mo=args.slow, executable_path=args.browser_path
		)
		context = browser.new_context(
			viewport={"width": 1440, "height": 900},
			record_video_dir=args.record_dir,
			record_video_size={"width": 1440, "height": 900} if args.record_dir else None,
		)
		page = context.new_page()
		page.on("pageerror", lambda error: errors.append(str(error)))
		page.on(
			"console",
			lambda m: (
				m.type == "error"
				and not any(ignored in m.text for ignored in IGNORED_ERRORS)
				and errors.append(m.text)
			),
		)

		try:
			login(page, args.url.rstrip("/"), args.user, password)
			run(page, args.url.rstrip("/"), lambda: page.wait_for_timeout(args.hold) if args.hold else None)
		finally:
			context.close()
			browser.close()

	if errors:
		print("Browser errors:\n" + "\n".join(errors), file=sys.stderr)
		return 1

	print("OK")
	return 0


if __name__ == "__main__":
	sys.exit(main())
