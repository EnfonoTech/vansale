"""Whitelisted file upload for mobile blobs (photos, signatures).

The ONE-uploader rule (`frappe-vue-pwa` §5 commandment 1) means the
client only ever calls this endpoint from a single place —
``resolveToRealUrl`` inside ``src/offline/photos.ts``. Every other
layer (PhotoSlot, SignaturePad, drain) defers to that one entry.

Filenames are sanitised server-side as a defence in depth; the client
also sanitises before writing to Filesystem on Android.
"""

from __future__ import annotations

import base64
import binascii
import re

import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.utils import now_datetime


_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitise(name: str) -> str:
    safe = _FILENAME_RE.sub("_", name or "").strip("_")
    return safe or f"upload_{int(now_datetime().timestamp())}.bin"


@frappe.whitelist(methods=["POST"])
def upload(
    filename: str,
    content_base64: str,
    attach_to_doctype: str | None = None,
    attach_to_name: str | None = None,
    is_private: int = 0,
) -> dict:
    """Save a base64-encoded blob as a Frappe File and return its URL.

    Arguments
    ---------
    filename
        Client-supplied name. Server re-sanitises before persisting.
    content_base64
        Pure base64 (no data-URL prefix).
    attach_to_doctype / attach_to_name
        Optional — links the File to a parent doc.
    is_private
        1 → stored under ``/private/files/`` (recommended for signatures).
    """
    if not content_base64:
        frappe.throw(_("File content required"))
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        frappe.throw(_("Invalid base64 payload: {0}").format(str(exc)))

    doc: File = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": _sanitise(filename),
            "is_private": int(bool(is_private)),
            "attached_to_doctype": attach_to_doctype,
            "attached_to_name": attach_to_name,
            "content": raw,
        }
    )
    doc.insert(ignore_permissions=False)
    return {
        "file_url": doc.file_url,
        "file_name": doc.file_name,
        "is_private": doc.is_private,
    }
