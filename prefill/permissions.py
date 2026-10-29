import frappe
from frappe.permissions import get_doctypes_with_read

# Permission types that only "use" a preset: seeing it in lists and applying it.
USE_PTYPES = frozenset({"read", "select", "print", "email", "export", "report"})


def is_system_manager(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _matches_share(row, user: str, roles: set[str]) -> bool:
	if row.share_type == "User":
		return row.user == user
	if row.share_type == "Role":
		return row.role in roles
	return False


def get_access(doc, user: str) -> dict:
	"""How `user` relates to the preset: owner, may use it, may edit it."""
	roles = set(frappe.get_roles(user))
	is_owner = doc.owner == user

	everyone = doc.scope == "Everyone" and bool(
		frappe.get_cached_doc("Form Presets Settings").allow_everyone_scope
	)
	matched = []
	if doc.scope == "Shared":
		matched = [row for row in doc.get("shares") or [] if _matches_share(row, user, roles)]

	return {
		"owner": is_owner,
		"use": is_owner or everyone or bool(matched),
		"edit": is_owner or any(row.can_edit for row in matched),
	}


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Hook for Form Preset. Frappe treats any falsy return as a denial, so always return a bool."""
	user = user or frappe.session.user

	if is_system_manager(user):
		return True

	# Rows that do not exist yet: the target-DocType create check runs in the controller.
	if ptype == "create":
		return True

	if doc.target_doctype and not frappe.has_permission(doc.target_doctype, "read", user=user):
		return False

	access = get_access(doc, user)
	if ptype in USE_PTYPES:
		return access["use"]
	if ptype == "write":
		return access["edit"]

	# delete, share, submit and everything else stays with the owner.
	return access["owner"]


def get_permission_query_conditions(user=None, doctype=None) -> str:
	user = user or frappe.session.user

	if is_system_manager(user):
		return ""

	readable = get_doctypes_with_read(user)
	if not readable:
		return "1=0"

	table = "`tabForm Preset`"
	escaped_user = frappe.db.escape(user)
	roles = ", ".join(frappe.db.escape(role) for role in frappe.get_roles(user))
	targets = ", ".join(frappe.db.escape(name) for name in readable)

	visible = [f"{table}.owner = {escaped_user}"]
	if frappe.get_cached_doc("Form Presets Settings").allow_everyone_scope:
		visible.append(f"{table}.scope = 'Everyone'")
	visible.append(
		f"({table}.scope = 'Shared' and exists (select 1 from `tabForm Preset Share` ps"
		f" where ps.parent = {table}.name and ps.parenttype = 'Form Preset'"
		f" and ((ps.share_type = 'User' and ps.user = {escaped_user})"
		f" or (ps.share_type = 'Role' and ps.role in ({roles})))))"
	)

	return f"{table}.target_doctype in ({targets}) and ({' or '.join(visible)})"
