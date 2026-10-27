"""Frappe app hooks — the one file Frappe reads to wire this app in.

Everything the framework calls on this app's behalf is registered here: the
assets that load on every Desk page, the permission hooks that keep one
user's transcripts out of another's reach, the installer, and the scheduler.

The permission hooks at the bottom are the load-bearing part.  ``Albanna
Conversation`` grants ``All`` read/write — that grant is what makes the
chat-access gate reachable for a user who is not a System Manager — and the
hooks registered here are what keep one user's chat history private.  Widening
the doctype without narrowing these hooks widens it for everyone, so both are
edited together or not at all.
"""

app_name = "albanna"
app_title = "Albanna"
app_publisher = "Albanna Software Solutions"
app_description = "ERPNext side chat — ask about your data in plain language"
app_email = "admin@albanna.dev"
app_license = "mit"

# Desk assets.
#
# The launcher is a small, framework-free file (no Vue) that asks the server
# whether the widget should render, places a launcher button and an empty
# panel on the page, and fetches the real Vue bundle on the first click.  A
# global hook is paid on every Desk page load, so the framework itself must
# not be in it — see ``public/js/albanna-side-chat.bundle.js``.
#
# The bundle name carries ``.bundle.`` on purpose: Frappe's ``include_style``
# resolves a hashed, content-addressed URL only for entries that contain
# ``.bundle.`` and do not start with ``/assets``.  A raw path is served from a
# URL that never changes under a one-year ``max-age``, which silently pins
# every returning user to the stylesheet they loaded first.
#
# Every entry here carries ``.bundle.`` for the same reason, and the reason
# is sharper for a script: an entry without it is passed through untouched
# and requested from the site root, where it does not exist.  The request
# 404s, the browser logs it, and nothing on the page says so — the feature
# is simply absent, on every page, for every user, forever.  The "Ask
# Albanna" button on a form and the "Ask Albanna" button on an error dialog
# were both missing for exactly that reason.
app_include_js = [
    "albanna-side-chat.bundle.js",
    "albanna-form-button.bundle.js",
    "albanna-error-button.bundle.js",
]
app_include_css = ["albanna-side-chat.bundle.css"]

# Chat history is private to the user who created it.  The doctype grants
# ``All`` read/write deliberately — without that grant a non-manager user
# could not reach the chat endpoints at all — and these two hooks are what
# make "All" mean "the owner, and a System Manager".
permission_query_conditions = {
    "Albanna Conversation": "albanna.services.conversation_service.get_permission_query_conditions",
}

has_permission = {
    "Albanna Conversation": "albanna.services.conversation_service.has_permission",
}

# The installer creates the Single settings row so the app is usable the
# moment it is installed, instead of failing on a missing document the first
# time somebody opens the widget.
after_install = "albanna.install.after_install"
after_migrate = "albanna.install.after_migrate"

# Chat logs are an audit trail, not a business record.  They are pruned by age
# so the table does not grow without bound; conversations are kept until the
# user deletes them.
scheduler_events = {
    "daily": [
        "albanna.tasks.prune_chat_logs",
    ],
}
