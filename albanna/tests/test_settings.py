"""The settings form's refusals, as the framework performs them.

The pure parsing lives in ``tests/test_disabled_tools.py`` — it runs
without a site.  What needs a site is the save: that a name which is not
a tool stops the document rather than reaching the table, that a name
which *is* a tool is kept, and that the list the model is finally shown
is the list the form accepted.

The framework rolls every test here back, so the site's own settings are
put back by hand as well: a suite that runs after this one reads them.
"""

from __future__ import annotations

import frappe

from albanna.core.tools import parse_tool_names
from albanna.services.settings_service import get_settings
from albanna.tests.base import AlbannaTestCase


class TestDisabledToolsOnSave(AlbannaTestCase):
    """What the form does with the operator's list of hidden tools."""

    def setUp(self):
        self._original = frappe.db.get_single_value("Albanna Settings", "disabled_tools") or ""
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.set_single_value("Albanna Settings", "disabled_tools", self._original)
        super().tearDown()

    def _settings(self, value):
        doc = frappe.get_doc("Albanna Settings")
        doc.disabled_tools = value
        return doc

    def test_a_name_that_is_not_a_tool_is_refused(self):
        doc = self._settings("create_doc, createe_doc")

        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_the_refusal_leaves_the_stored_list_alone(self):
        """A refused save is not a half-applied save."""

        frappe.db.set_single_value("Albanna Settings", "disabled_tools", "delete_doc")
        doc = self._settings("deletee_doc")

        with self.assertRaises(frappe.ValidationError):
            doc.save()

        self.assertEqual(
            frappe.db.get_single_value("Albanna Settings", "disabled_tools"), "delete_doc"
        )

    def test_a_tool_name_is_accepted(self):
        doc = self._settings("delete_doc, create_doc")
        doc.save()

        self.assertEqual(
            parse_tool_names(frappe.db.get_single_value("Albanna Settings", "disabled_tools")),
            ("delete_doc", "create_doc"),
        )

    def test_ask_question_may_be_hidden(self):
        """It is a real tool, so the list naming it is valid.

        The save warns — it is the tool the assistant asks the reader
        with — and a warning is not a refusal.
        """

        doc = self._settings("ask_question")
        doc.save()

        self.assertEqual(
            parse_tool_names(frappe.db.get_single_value("Albanna Settings", "disabled_tools")),
            ("ask_question",),
        )

    def test_the_form_and_the_model_see_the_same_list(self):
        """One parser, or the form accepts a list the runtime reads as another."""

        doc = self._settings("delete_doc, create_doc")
        doc.save()

        self.assertEqual(get_settings(refresh=True).disabled_tools, ("delete_doc", "create_doc"))

    def test_the_whitespace_list_the_operator_wrote_is_the_list_kept(self):
        """``a b`` is one entry, and it is refused as one entry."""

        doc = self._settings("create_doc delete_doc")

        with self.assertRaises(frappe.ValidationError):
            doc.save()
