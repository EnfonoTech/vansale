# # Copyright (c) 2026, enfono and contributors
# # For license information, please see license.txt

import frappe


def execute(filters=None):
    return get_columns(), get_data(filters)


def get_columns():
    return [
        { "label": "User", "fieldname": "owner", "fieldtype": "Link", "options": "User", "width": 180 },
        { "label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 150 },
        { "label": "DocType", "fieldname": "doctype", "fieldtype": "Data", "width": 150 },
        { "label": "Document", "fieldname": "name", "fieldtype": "Dynamic Link", "options": "doctype", "width": 200 },
        { "label": "Status", "fieldname": "workflow_state", "fieldtype": "Data", "width": 150 },
        { "label": "Created Date", "fieldname": "creation", "fieldtype": "Datetime", "width": 180 }
    ]


def get_data(filters):
    filters = filters or {}

    if filters.get("doctype"):
        return get_doctype_data(filters.get("doctype"), filters)

    workflows = frappe.db.get_all("Workflow",
        filters={"is_active": 1},
        fields=["document_type"]
    )

    all_data = []
    seen = set()
    for w in workflows:
        dt = w.document_type
        if not dt or dt in seen:
            continue
        seen.add(dt)
        try:
            all_data.extend(get_doctype_data(dt, filters))
        except Exception:
            continue

    all_data.sort(key=lambda x: x.get("creation") or "", reverse=True)
    return all_data


def get_doctype_data(doctype, filters):
    if not frappe.db.has_column(doctype, "workflow_state"):
        return []

    has_company = frappe.db.has_column(doctype, "company")
    conditions = "workflow_state = 'Pending'"
    values = {}

    if filters.get("company") and has_company:
        conditions += " AND company = %(company)s"
        values["company"] = filters["company"]

    if filters.get("from_date"):
        conditions += " AND creation >= %(from_date)s"
        values["from_date"] = filters["from_date"]

    if filters.get("to_date"):
        conditions += " AND creation <= %(to_date)s"
        values["to_date"] = filters["to_date"]

    fields = ("company, " if has_company else "") + "name, workflow_state, owner, creation"
    data = frappe.db.sql(f"""
        SELECT {fields} FROM `tab{doctype}`
        WHERE {conditions} ORDER BY creation DESC
    """, values, as_dict=True)

    for d in data:
        d["doctype"] = doctype
        if not has_company:
            d["company"] = ""

    return data


@frappe.whitelist()
def get_workflow_actions(doctype):
    wf = frappe.db.get_all("Workflow",
        filters={"document_type": doctype, "is_active": 1},
        fields=["name"], limit=1)

    if not wf:
        return []

    seen, actions = set(), []
    for t in frappe.get_doc("Workflow", wf[0].name).transitions:
        if t.action and t.action not in seen:
            seen.add(t.action)
            actions.append(t.action)
    return actions


@frappe.whitelist()
def get_all_workflow_actions():
    """Return the union of actions across all active workflows."""
    workflows = frappe.db.get_all("Workflow",
        filters={"is_active": 1},
        fields=["name"]
    )

    seen, actions = set(), []
    for w in workflows:
        try:
            for t in frappe.get_doc("Workflow", w.name).transitions:
                if t.action and t.action not in seen:
                    seen.add(t.action)
                    actions.append(t.action)
        except Exception:
            continue
    return actions


@frappe.whitelist()
def apply_bulk_workflow(docs, action):
    import json
    from frappe.model.workflow import apply_workflow

    results = []
    for d in json.loads(docs):
        try:
            apply_workflow(frappe.get_doc(d["doctype"], d["name"]), action)
            results.append(f" {d['name']} — Success")
        except Exception as e:
            results.append(f" {d['name']} — {str(e)}")

    frappe.db.commit()
    return "<br>".join(results)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_workflow_doctypes(doctype, txt, searchfield, start, page_len, filters):
    workflows = frappe.db.get_all("Workflow",
        filters={"is_active": 1},
        fields=["document_type"],
        limit=100
    )

    doctypes = [[w.document_type, w.document_type] for w in workflows
                if w.document_type and txt.lower() in w.document_type.lower()]

    return doctypes


@frappe.whitelist()
def get_pending_approval_count(user=None):
    """
    Returns the count of pending workflow documents that the given user
    (default: logged-in user) is permitted to approve.

    A user is considered an approver if their role matches the
    `allow_edit` role defined on the 'Pending' workflow state.
    Administrator sees all pending documents.
    """
    user = user or frappe.session.user

    if user == "Administrator":
        return _count_all_pending()

    user_roles = set(frappe.get_roles(user))

    workflows = frappe.db.get_all("Workflow",
        filters={"is_active": 1},
        fields=["name", "document_type"]
    )

    total = 0
    seen = set()
    for w in workflows:
        dt = w.document_type
        if not dt or dt in seen:
            continue
        seen.add(dt)

        if not frappe.db.has_column(dt, "workflow_state"):
            continue

        try:
            wf_doc = frappe.get_cached_doc("Workflow", w.name)
        except Exception:
            continue

        # Collect roles allowed to act on the Pending state
        approver_roles = set()
        for state in wf_doc.states:
            if state.state == "Pending" and state.allow_edit:
                approver_roles.add(state.allow_edit)

        # Skip this doctype if the user has none of the approver roles
        if approver_roles and not (user_roles & approver_roles):
            continue

        try:
            total += frappe.db.count(dt, filters={"workflow_state": "Pending"}) or 0
        except Exception:
            continue

    return total


def _count_all_pending():
    workflows = frappe.db.get_all("Workflow",
        filters={"is_active": 1},
        fields=["document_type"]
    )
    total = 0
    seen = set()
    for w in workflows:
        dt = w.document_type
        if not dt or dt in seen:
            continue
        seen.add(dt)
        if not frappe.db.has_column(dt, "workflow_state"):
            continue
        try:
            total += frappe.db.count(dt, filters={"workflow_state": "Pending"}) or 0
        except Exception:
            continue
    return total