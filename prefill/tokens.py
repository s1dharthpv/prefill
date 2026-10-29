import frappe
from frappe import _
from frappe.utils import add_days, get_first_day, get_last_day, now, nowdate


def resolve(token: dict, df) -> tuple[str | None, str | None]:
	"""Turn a `$dyn` object into a value for `df`. Returns (value, None), or (None, reason) if it cannot resolve."""
	name = token["$dyn"]

	if name == "today":
		day = add_days(nowdate(), token.get("days", 0))
		return (f"{day} 00:00:00" if df.fieldtype == "Datetime" else day), None

	if name == "now":
		return now(), None

	if name == "month_start":
		return str(get_first_day(nowdate())), None

	if name == "month_end":
		return str(get_last_day(nowdate())), None

	if name == "me":
		return frappe.session.user, None

	if name == "default_company":
		return _default_company()

	return None, _("Unknown dynamic value")


def _default_company() -> tuple[str | None, str | None]:
	if not frappe.db.exists("DocType", "Company"):
		return None, _("Company is not available on this site")

	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		return None, _("No default company is set")

	return company, None
