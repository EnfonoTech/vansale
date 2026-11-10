import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_transfer_progress(material_request):
    """Return per-item transfer progress for a Material Request.

    For each item row: required_qty, transferred_qty (submitted Material Transfer
    Stock Entries), pending_qty, and percent_complete.
    """
    if not material_request:
        frappe.throw(_("Material Request is required"))

    frappe.has_permission("Material Request", "read", doc=material_request, throw=True)

    rows = frappe.db.sql(
        """
        SELECT
            mri.name        AS mr_item,
            mri.idx         AS idx,
            mri.item_code   AS item_code,
            mri.item_name   AS item_name,
            mri.qty         AS required_qty,
            mri.uom         AS uom,
            mri.warehouse   AS warehouse,
            COALESCE(SUM(
                CASE WHEN se.docstatus = 1 THEN sed.qty ELSE 0 END
            ), 0) AS transferred_qty
        FROM `tabMaterial Request Item` mri
        LEFT JOIN `tabStock Entry Detail` sed
            ON  sed.material_request_item = mri.name
        LEFT JOIN `tabStock Entry` se
            ON  se.name = sed.parent
            AND se.stock_entry_type = 'Material Transfer'
        WHERE mri.parent = %s
        GROUP BY mri.name
        ORDER BY mri.idx
        """,
        (material_request,),
        as_dict=True,
    )

    for r in rows:
        r.required_qty = flt(r.required_qty)
        r.transferred_qty = flt(r.transferred_qty)
        r.pending_qty = max(flt(r.required_qty - r.transferred_qty), 0)
        r.percent_complete = (
            round(min(r.transferred_qty / r.required_qty * 100, 100), 1)
            if r.required_qty
            else 0
        )

    return rows
