"""The app's file upload (`vansale.api.file_upload`) without a site.

`upload` is a public endpoint: an unattached upload (the offline photo and
signature flow sends only filename, content_base64 and is_private) keeps
working as before, and attaching to a document needs write permission on it.
`approvals_extra.attach` runs its own guard (an open approval the caller may
act on, and read permission) and then saves through `_save_file`, so an
approver who may not write the document can still attach.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_file_upload -v
"""

from __future__ import annotations

import base64
import types
import unittest
from unittest.mock import MagicMock

import frappe

from vansale.api import file_upload
from vansale.steelforce import approvals, approvals_extra
from vansale.tests.test_approvals_api import ME, SiteFreeCase
from vansale.tests.test_approvals_extra import FakeFile, action_row

ABC = base64.b64encode(b"ABC").decode()


class UploadCase(SiteFreeCase):
    """Every File built is recorded in `self.files` (none is saved); `self.can`
    holds the `(doctype, ptype)` pairs the user has."""

    def setUp(self):
        super().setUp()
        frappe.local.session.user = ME
        self.files: list[FakeFile] = []
        self.can: set[tuple[str, str]] = set()
        self.has_permission = self._patch(
            "frappe.has_permission",
            side_effect=lambda doctype, ptype="read", doc=None, **kwargs: (doctype, ptype) in self.can,
        )
        self.get_doc = self._patch("frappe.get_doc", side_effect=self._get_doc)

    def _get_doc(self, first, name=None, *args, **kwargs):
        if isinstance(first, dict):
            self.assertEqual(first["doctype"], "File")
            file = FakeFile(first)
            self.files.append(file)
            return file
        if first == approvals.PM_ACTION:
            return types.SimpleNamespace(doctype=first, name=name)
        raise AssertionError(f"unexpected get_doc({first!r}, {name!r})")


class TestUploadEndpoint(unittest.TestCase):
    def test_upload_is_a_post_endpoint_and_the_saver_is_not_an_endpoint(self):
        self.assertIn(file_upload.upload, frappe.whitelisted)
        self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[file_upload.upload], ["POST"])
        self.assertNotIn(file_upload.upload, frappe.guest_methods)
        self.assertNotIn(file_upload._save_file, frappe.whitelisted)


class TestUnattachedUpload(UploadCase):
    def test_the_offline_photo_and_signature_call_still_works(self):
        for is_private in (0, 1):
            with self.subTest(is_private=is_private):
                result = file_upload.upload(filename="photo 1.jpg", content_base64=ABC, is_private=is_private)

                file = self.files[-1]
                self.assertEqual(
                    result,
                    {"file_url": file.file_url, "file_name": "photo_1.jpg", "is_private": is_private},
                )
                self.assertEqual(file.values["content"], b"ABC")
                self.assertIsNone(file.values["attached_to_doctype"])
                self.assertIsNone(file.values["attached_to_name"])
                self.assertEqual(file.insert_kwargs, {"ignore_permissions": False})
        self.has_permission.assert_not_called()

    def test_a_payload_that_is_not_base64_or_empty_is_refused(self):
        for content in ("not base64 !!", ""):
            with self.subTest(content=content):
                with self.assertRaises(frappe.ValidationError):
                    file_upload.upload("a.jpg", content)
        self.assertEqual(self.files, [])


class TestAttachedUpload(UploadCase):
    def test_attaching_to_a_document_the_user_may_not_write_is_refused_and_no_file_is_made(self):
        self.can = {("Sales Invoice", "read")}

        with self.assertRaises(frappe.PermissionError):
            file_upload.upload("scan.pdf", ABC, attach_to_doctype="Sales Invoice", attach_to_name="SINV-1")

        self.has_permission.assert_called_once_with("Sales Invoice", "write", doc="SINV-1")
        self.assertEqual(self.files, [])

    def test_attaching_to_a_document_the_user_may_write_works(self):
        self.can = {("Sales Invoice", "write")}

        result = file_upload.upload(
            "scan.pdf", ABC, attach_to_doctype="Sales Invoice", attach_to_name="SINV-1", is_private=1
        )

        (file,) = self.files
        self.assertEqual(result["file_url"], "/private/files/scan.pdf")
        self.assertEqual(
            (file.values["attached_to_doctype"], file.values["attached_to_name"]), ("Sales Invoice", "SINV-1")
        )

    def test_half_a_target_is_refused_and_no_file_is_made(self):
        self.can = {("Sales Invoice", "write")}

        for doctype, name in (("Sales Invoice", None), (None, "SINV-1"), ("Sales Invoice", ""), ("", "SINV-1")):
            with self.subTest(doctype=doctype, name=name):
                with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
                    file_upload.upload("scan.pdf", ABC, attach_to_doctype=doctype, attach_to_name=name)
        self.assertEqual(self.files, [])

    def test_the_permission_is_checked_before_the_payload_is_looked_at(self):
        with self.assertRaises(frappe.PermissionError):
            file_upload.upload("scan.pdf", "not base64 !!", attach_to_doctype="Sales Invoice", attach_to_name="SINV-1")


class TestApproverAttach(UploadCase):
    """sara holds the open approval WA-1 on SINV-1 and may read it, but not
    write it: `attach` still stores the file, through `_save_file`."""

    def setUp(self):
        super().setUp()
        self.can = {("Sales Invoice", "read")}
        self._patch("vansale.steelforce.approvals.is_available", return_value=True)
        self.pm = MagicMock(name="pm")
        self.pm.hidden_doctypes.return_value = []
        self.pm.can_act_on.side_effect = lambda action_doc, user: user == ME and action_doc.name == "WA-1"
        self._patch("vansale.steelforce.approvals._pm", return_value=self.pm)
        self._patch("frappe.get_all", side_effect=lambda doctype, **kwargs: [frappe._dict(action_row("WA-1"))])
        frappe.local.db.get_value.side_effect = lambda doctype, filters, fieldname, **kwargs: (
            "FILE-0001" if doctype == "File" and filters["file_url"] == "/private/files/scan.pdf" else None
        )

    def test_an_approver_who_may_not_write_the_document_can_still_attach(self):
        result = approvals_extra.attach("Sales Invoice", "SINV-1", "scan.pdf", ABC)

        self.assertEqual(result, {"name": "FILE-0001", "url": "/private/files/scan.pdf"})
        (file,) = self.files
        self.assertEqual(file.values["is_private"], 1)
        self.assertEqual(
            (file.values["attached_to_doctype"], file.values["attached_to_name"]), ("Sales Invoice", "SINV-1")
        )
        self.assertNotIn("write", [c.args[1] for c in self.has_permission.call_args_list])

    def test_without_the_approval_nothing_is_stored(self):
        self.pm.can_act_on.side_effect = lambda action_doc, user: False

        with self.assertRaises(frappe.PermissionError):
            approvals_extra.attach("Sales Invoice", "SINV-1", "scan.pdf", ABC)
        self.assertEqual(self.files, [])


if __name__ == "__main__":
    unittest.main()
