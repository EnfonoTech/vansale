import frappe
import re

def natural_sort_key(item_name):
    """Sort key that handles numeric parts correctly for size ordering."""
    parts = re.split(r'(\d+\.?\d*)', str(item_name))
    result = []
    for part in parts:
        try:
            result.append(float(part))
        except ValueError:
            result.append(part.lower())
    return result

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_search_sorted(doctype, txt, searchfield, start, page_len, filters):
    """Custom item search that sorts results by size (natural/numeric order)."""
    
    conditions = ""
    if txt:
        conditions = """
            AND (
                item.item_code LIKE %(txt)s
                OR item.item_name LIKE %(txt)s
                OR item.description LIKE %(txt)s
                OR EXISTS (
                    SELECT 1 FROM `tabItem Barcode` ib
                    WHERE ib.parent = item.item_code
                    AND ib.barcode LIKE %(txt)s
                )
            )
        """

    results = frappe.db.sql(
        f"""
        SELECT
            item.item_code,
            item.item_name,
            item.item_group,
            item.description,
            item.stock_uom
        FROM `tabItem` item
        WHERE
            item.disabled = 0
            AND item.has_variants = 0
            {conditions}
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        {
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len,
        },
        as_dict=True
    )

    # Sort results by natural/numeric order of item_name
    results.sort(key=lambda r: natural_sort_key(r.get("item_name", "")))

    return [
        (r.item_code, r.item_name, r.item_group or "", r.description or "")
        for r in results
    ]