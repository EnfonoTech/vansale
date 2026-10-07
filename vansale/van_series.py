"""Per-van document numbering.

Ports the RMAX branch-series pattern down to the van. Each Vansale
Configuration carries a `doc_prefix` (e.g. ``VAN1-``); from it we generate one
series template per document type and auto-pick the right one when the driver's
app creates a document.

**The trap that makes this non-obvious.** Frappe keys the `tabSeries` counter on
the *resolved prefix*, so a template like ``VAN1-.YYYY.-.####`` used for both
Sales Invoice and Payment Entry gives those two doctypes ONE SHARED counter —
invoice 41 followed by receipt 42. Every template therefore embeds a
per-doctype abbreviation: ``VAN1-INV-.YYYY.-.####``, ``VAN1-PE-.YYYY.-.####``.
RMAX shipped the shared-counter version first and had to strip it; do not
"simplify" the abbreviation away.

Returns get their own row (``use_for_return``) and their own abbreviation, so
credit notes do not consume invoice numbers.

Three pieces:

1. :func:`sync_van_series` — idempotent provisioner. Generates the child rows
   and appends every van's template to each doctype's ``naming_series``
   Property Setter options. Frappe validates a saved document's series against
   that options list, so without step 2 the series we set would be rejected.
2. :func:`set_naming_series_from_van` — ``before_insert`` hook. Picks the row
   for the creating user's van and the document's return flag.
3. Called from ``setup.after_migrate``.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

# (doctype, normal abbreviation, return abbreviation or None)
SERIES_TARGETS: list[tuple[str, str, str | None]] = [
    ("Sales Invoice", "INV", "CN"),   # CN = credit note
    ("Payment Entry", "PE", None),
    ("Stock Entry", "SE", None),
]

# Roles trusted to pick a series by hand on the desk. Their choice is not
# overridden — mirrors RMAX, where finance legitimately posts on another
# branch's series during corrections.
TRUSTED_ROLES = {"System Manager", "Accounts Manager", "Stock Manager"}

SERIES_SUFFIX = "-.YYYY.-.####"


def normalise_prefix(prefix: str | None) -> str:
    """Upper-case, trimmed, exactly one trailing dash. Empty stays empty."""
    p = (prefix or "").strip().upper().rstrip("-")
    return f"{p}-" if p else ""


def template_for(prefix: str, abbrev: str) -> str:
    return f"{normalise_prefix(prefix)}{abbrev}{SERIES_SUFFIX}"


# ---------------------------------------------------------------- provision --


def sync_van_series() -> None:
    """Generate series rows + Property Setter options for every van.

    Idempotent; safe on every ``after_migrate``.
    """
    vans = frappe.get_all(
        "Vansale Configuration",
        filters={"doc_prefix": ["is", "set"]},
        fields=["name", "doc_prefix"],
    )
    wanted_by_doctype: dict[str, set[str]] = {dt: set() for dt, _a, _r in SERIES_TARGETS}

    for van in vans:
        prefix = normalise_prefix(van.doc_prefix)
        if not prefix:
            continue
        rows: list[dict] = []
        for doctype, abbrev, ret_abbrev in SERIES_TARGETS:
            normal = template_for(prefix, abbrev)
            rows.append({"parent_doctype": doctype, "naming_series": normal, "use_for_return": 0})
            wanted_by_doctype[doctype].add(normal)
            if ret_abbrev:
                ret = template_for(prefix, ret_abbrev)
                rows.append({"parent_doctype": doctype, "naming_series": ret, "use_for_return": 1})
                wanted_by_doctype[doctype].add(ret)
        _replace_rows(van.name, rows)

    for doctype, templates in wanted_by_doctype.items():
        if templates:
            extend_series_options(doctype, templates)


def _replace_rows(van: str, rows: list[dict]) -> None:
    """Rewrite the van's series table only when it actually differs.

    Comparing first keeps `after_migrate` from bumping `modified` on every van
    on every deploy, which would make the Version history useless.
    """
    existing = frappe.get_all(
        "Vansale Naming Series",
        filters={"parent": van, "parenttype": "Vansale Configuration"},
        fields=["parent_doctype", "naming_series", "use_for_return"],
    )
    current = {(r.parent_doctype, r.naming_series, cint(r.use_for_return)) for r in existing}
    target = {(r["parent_doctype"], r["naming_series"], cint(r["use_for_return"])) for r in rows}
    if current == target:
        return

    doc = frappe.get_doc("Vansale Configuration", van)
    doc.set("naming_series_table", [])
    for r in rows:
        doc.append("naming_series_table", r)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_validate_update_after_submit = True
    doc.flags.ignore_version = True
    doc.save(ignore_permissions=True)


def extend_series_options(doctype: str, templates: set[str]) -> None:
    """Append templates to the doctype's `naming_series` options.

    Frappe validates a document's `naming_series` against this list, so a
    series we set but never registered here is rejected at insert. Existing
    options are preserved — other apps (and the site's own series) live in the
    same list.
    """
    meta_field = frappe.get_meta(doctype).get_field("naming_series")
    if not meta_field:
        return

    ps_name = f"{doctype}-naming_series-options"
    existing_ps = frappe.db.get_value("Property Setter", ps_name, "value")
    base = existing_ps if existing_ps is not None else (meta_field.options or "")
    current = [o for o in (base or "").split("\n") if o.strip()]
    merged = current + [t for t in sorted(templates) if t not in current]
    if merged == current:
        return

    value = "\n".join(merged)
    if existing_ps is not None:
        frappe.db.set_value("Property Setter", ps_name, "value", value)
    else:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": doctype,
            "field_name": "naming_series",
            "property": "options",
            "property_type": "Text",
            "value": value,
        }).insert(ignore_permissions=True)
    frappe.clear_cache(doctype=doctype)


# --------------------------------------------------------------------- hook --


def set_naming_series_from_van(doc, method=None) -> None:
    """`before_insert`: stamp the creating user's van series onto the document.

    Runs for app-created and desk-created documents alike, which is why it is a
    hook rather than a line inside each API endpoint.

    Left alone when:
      * the van has no prefix — the site's normal series applies;
      * the series already starts with this van's prefix — already correct, and
        re-stamping would be a no-op that hides a manual choice;
      * the user holds a trusted role AND picked a series by hand.
    """
    if not doc.meta.get_field("naming_series"):
        return

    van = frappe.db.get_value(
        "Vansale Configuration User", {"user": frappe.session.user}, "parent"
    )
    if not van:
        return

    prefix = normalise_prefix(frappe.db.get_value("Vansale Configuration", van, "doc_prefix"))
    if not prefix:
        return

    current = (doc.get("naming_series") or "").strip()
    if current.startswith(prefix):
        return
    from vansale.api.me import is_office_user

    if current and is_office_user(default_roles=TRUSTED_ROLES):
        return

    is_return = cint(doc.get("is_return"))
    row = frappe.db.get_value(
        "Vansale Naming Series",
        {
            "parent": van,
            "parenttype": "Vansale Configuration",
            "parent_doctype": doc.doctype,
            "use_for_return": 1 if is_return else 0,
        },
        "naming_series",
    )
    # A doctype with no return-specific row falls back to its normal row rather
    # than silently keeping the site series.
    if not row and is_return:
        row = frappe.db.get_value(
            "Vansale Naming Series",
            {
                "parent": van,
                "parenttype": "Vansale Configuration",
                "parent_doctype": doc.doctype,
                "use_for_return": 0,
            },
            "naming_series",
        )
    if row:
        doc.naming_series = row
