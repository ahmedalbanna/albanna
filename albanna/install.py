"""Installation and migration.

The only thing the installer has to do is make sure the settings Single
exists, so that a freshly installed app is usable rather than failing on a
missing document the first time somebody opens the widget.

The defaults it writes are deliberately conservative: the chat is off for
every account that does not hold the ``Albanna User`` role, and the model
is a real provider with no key, so the first thing an administrator sees
when they open the settings is a clear "this needs a key" rather than a
widget that silently fails.
"""

import frappe


def after_install():
    """Create the settings document with its defaults."""
    _ensure_settings()
    _ensure_role()


def after_migrate():
    """Keep the settings document present across migrations."""
    _ensure_settings()
    _ensure_role()


def _ensure_settings() -> None:
    if frappe.db.exists("Albanna Settings", "Albanna Settings"):
        return

    try:
        doc = frappe.get_single("Albanna Settings")
    except Exception:
        doc = frappe.new_doc("Albanna Settings")

    for fieldname, value in _DEFAULTS.items():
        if not doc.get(fieldname):
            doc.set(fieldname, value)

    doc.flags.ignore_permissions = True
    doc.insert(ignore_if_duplicate=True)


def _ensure_role() -> None:
    """The role that grants the chat, and the one the permission rows name.

    It is shipped here rather than only in the patch, because a fresh
    install never runs the patch and would otherwise have no role for the
    rows to name.  Idempotent.
    """
    if frappe.db.exists("Role", "Albanna User"):
        return

    role = frappe.new_doc("Role")
    role.role_name = "Albanna User"
    role.desk_access = 1
    role.flags.ignore_permissions = True
    role.insert(ignore_if_duplicate=True)
    frappe.db.commit()
#:
#: Conservative on purpose: the chat is off for every account that does not
#: hold the ``Albanna User`` role, and the model is a real provider with no
#: key, so the first thing an administrator sees when they open the settings
#: is a clear "this needs a key" rather than a widget that silently fails.
#:
#: The provider is the one this deployment uses.  It is an OpenAI-compatible
#: endpoint, so the same settings work against any other.
_DEFAULTS = {
    "provider_kind": "openai",
    "base_url": "https://api.hcnsec.cn/v1",
    "model": "MiniMax-M3.1-Flash",
    "fallback_enabled": 1,
    "fallback_kind": "openai",
    "fallback_base_url": "https://api.hcnsec.cn/v1",
    "fallback_model": "longcat-2.5",
    "max_tokens": 8192,
    "enabled": 1,
    "max_tool_rounds": 25,
    "history_limit": 50,
    "turn_timeout": 600,
    "turns_per_minute": 6,
}
