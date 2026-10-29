from frappe.utils import cint

from prefill.exclusions import get_excluded_doctypes, get_settings


def boot_session(bootinfo):
	"""Tell the desk whether to show the Presets UI, so forms need no server call to decide."""
	settings = get_settings()
	bootinfo.form_presets = {
		"enabled": cint(settings.enabled),
		"allow_everyone": cint(settings.allow_everyone_scope),
		"excluded": sorted(get_excluded_doctypes()),
	}
