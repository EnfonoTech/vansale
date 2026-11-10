# apps/vansale/vansale/sf_trading/api/payment_automation.py
"""Payment automation engine — scheduled supplier payments, four steps deep.

Feature set follows resilient-tech/payments-processor (GPL-3.0):
weekday + time-of-day gating with a last_execution guard, due-date offset, per-run party cap,
generate/submit money thresholds, hold and disabled party guards, foreign-currency exclusion,
duplicate protection, and a role-targeted notification. Extended beyond that app in two ways
the client asked for: the run works at **Payment Advice** level as well as Payment Entry, and
it can stop at any of four steps —

    1. create Payment Advice   (from outstanding Purchase Invoices)
    2. submit Payment Advice
    3. create Payment Entry    (from the submitted advice)
    4. submit Payment Entry

Provenance: the automation feature set is derived from resilient-tech/payments-processor,
which is licensed GNU GPL-3.0. Recorded here so the origin of the design is never lost.

The sweep and creation are NOT reimplemented here — this calls the same
`vansale.sf_trading.api.payment_advice_builder` functions the desk builder uses, so a scheduled run
and a human run cannot drift apart.

Scheduler entry: `run_due_automations`, hooked on `all` (every tick) and gated internally.
"""

import frappe
from frappe import _
from frappe.utils import (
    cint,
    flt,
    get_datetime,
    get_time,
    getdate,
    now_datetime,
)

from vansale.sf_trading.api import payment_advice_builder as builder

ALERT_EVENT = "sf_invoice_overdue_alert"  # the live chime + toast + bell channel
NOTIFICATION_REPORT = "Payment Advice"


# ── scheduler ────────────────────────────────────────────────────────────────────

def run_due_automations():
    """Scheduler tick: run every enabled configuration whose window has arrived.

    Hooked on `all` rather than `daily` so a configuration can name its own time of day.
    Each run is fenced by `last_execution`, so a tick storm cannot double-run one setting.
    """
    names = frappe.get_all(
        "Payment Automation Settings", filters={"enabled": 1}, pluck="name"
    )
    for name in names:
        try:
            if is_due(name):
                # Claim the slot BEFORE enqueuing. The `all` event fires every few minutes;
                # without this the next tick would still see is_due() == True while the job
                # sits in the queue, enqueue a second run, and create duplicate advices.
                frappe.db.set_value(
                    "Payment Automation Settings", name, "last_execution", now_datetime(),
                    update_modified=False,
                )
                frappe.db.commit()

                frappe.enqueue(
                    "vansale.sf_trading.api.payment_automation.run_automation",
                    queue="long",
                    timeout=1800,
                    enqueue_after_commit=True,
                    job_name="payment_automation_%s" % name,
                    settings_name=name,
                    force=1,  # the window was already checked and claimed here
                )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "sf_trading: payment automation dispatch failed")


def is_due(settings_name, at=None):
    """True when this configuration should run now and has not already run today."""
    setting = frappe.get_doc("Payment Automation Settings", settings_name)
    if not cint(setting.enabled) or not setting.highest_enabled_step():
        return False

    at = get_datetime(at or now_datetime())

    if not setting.runs_today(at.strftime("%A")):
        return False

    if setting.processing_time and at.time() < get_time(setting.processing_time):
        return False

    if setting.last_execution and getdate(setting.last_execution) >= getdate(at):
        return False

    return True


# ── run ──────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def run_automation(settings_name: str, force: int = 0, dry_run: int = None):
    """Execute one configuration.

    Safe to call by hand: `force` skips the schedule window, and `dry_run` overrides the
    stored flag for a single run (passed explicitly, since this function re-reads the
    document and would otherwise lose an in-memory override).
    """
    setting = frappe.get_doc("Payment Automation Settings", settings_name)
    setting.check_permission("read")

    if not cint(force) and not is_due(settings_name):
        return {"skipped": True, "reason": _("Not due yet")}

    is_dry = cint(setting.dry_run) if dry_run is None else cint(dry_run)

    summary = frappe._dict(
        settings=settings_name,
        company=setting.company,
        dry_run=bool(is_dry),
        advices=[],
        submitted_advices=[],
        payment_entries=[],
        submitted_payment_entries=[],
        skipped=[],
        errors=[],
        total_amount=0.0,
    )

    try:
        groups = _sweep(setting, summary)
        if not summary.dry_run:
            _create(setting, groups, summary)
    except Exception as exc:
        summary.errors.append(str(exc))
        frappe.log_error(frappe.get_traceback(), "sf_trading: payment automation run failed")

    # stamp the run even when it found nothing, so it does not retry every tick all day
    frappe.db.set_value(
        "Payment Automation Settings", settings_name, "last_execution", now_datetime(),
        update_modified=False,
    )
    frappe.db.commit()

    _notify(setting, summary)
    return summary


def _sweep(setting, summary):
    """Ask the builder what is payable, then apply the run's own caps and thresholds."""
    filters = {
        "company": setting.company,
        "party_type": setting.party_type or "Supplier",
        "due_before": builder.get_due_cutoff(setting.due_date_offset),
        "minimum_total": flt(setting.minimum_amount) or builder.DEFAULT_FLOOR,
        "min_ageing": cint(setting.min_ageing),
        "cost_center": setting.cost_center,
        "branch": setting.branch,
        "include_orders": cint(setting.include_orders),
        "ignore_on_hold": cint(setting.ignore_blocked_parties),
    }

    data = builder.get_builder_data(filters)
    company_currency = frappe.db.get_value("Company", setting.company, "default_currency")

    payable = []
    for group in data["groups"]:
        if group["skip"]:
            summary.skipped.append(
                {"party": group["party"], "reason": group["skip"], "label": group["skip_label"]}
            )
            continue

        if cint(setting.exclude_foreign_currency) and [
            c for c in group["currencies"] if c and c != company_currency
        ]:
            summary.skipped.append(
                {"party": group["party"], "reason": "foreign_currency", "label": _("Foreign currency")}
            )
            continue

        if flt(setting.advice_threshold) and flt(group["total_outstanding"]) > flt(
            setting.advice_threshold
        ):
            summary.skipped.append(
                {
                    "party": group["party"],
                    "reason": "above_advice_threshold",
                    "label": _("Above the advice threshold"),
                }
            )
            continue

        if _party_opted_out(setting.party_type, group["party"]):
            summary.skipped.append(
                {"party": group["party"], "reason": "party_opted_out", "label": _("Automation disabled on the party")}
            )
            continue

        payable.append(group)

    cap = cint(setting.max_parties_per_run) or 25
    if len(payable) > cap:
        for group in payable[cap:]:
            summary.skipped.append(
                {"party": group["party"], "reason": "over_run_cap", "label": _("Over the per-run cap")}
            )
        payable = payable[:cap]

    summary.considered = len(payable)
    return payable


def _party_opted_out(party_type, party):
    """A party can be excluded from automation without touching the configuration."""
    field = "custom_disable_auto_payment"
    if not frappe.get_meta(party_type).has_field(field):
        return False
    return bool(cint(frappe.db.get_value(party_type, party, field)))


def _create(setting, groups, summary):
    """Walk the four steps, each gated by the previous one and its own threshold."""
    if not cint(setting.auto_create_advice) or not groups:
        return

    options = {
        "company": setting.company,
        "party_type": setting.party_type or "Supplier",
        "mode_of_payment": setting.mode_of_payment,
        "bank_account": setting.bank_account,
        "cost_center": setting.cost_center,
        "approver": setting.approver,
        "remarks": setting.remarks or _("Raised automatically by %s") % setting.name,
        "auto_generated": 1,
        "run_now": 1,  # already inside a background job
    }

    selections = [
        {"party": g["party"], "references": g["rows"], "bank_account": g["bank_account"]}
        for g in groups
    ]

    result = builder.create_advices(selections, options)
    summary.advices = result.get("created") or []
    summary.total_amount = flt(result.get("total_amount"))
    for failure in result.get("failed") or []:
        summary.errors.append("%s: %s" % (failure.get("party"), failure.get("error")))

    if not cint(setting.auto_submit_advice):
        return

    # An approval workflow outranks the automation: raising drafts is helpful, submitting
    # them behind the approvers' backs is not. Say so in the summary rather than silently
    # doing nothing or blowing up on the workflow's permissions.
    from vansale.sf_trading.doctype.payment_advice.payment_advice import (
        workflow_controls_submission,
    )

    if workflow_controls_submission(setting.company):
        summary.skipped.append(
            {
                "party": None,
                "reason": "workflow_controls_submission",
                "label": _(
                    "Advices left as drafts — a PM Workflow governs Payment Advice approval"
                ),
            }
        )
        return

    for created in summary.advices:
        try:
            _advance_one(setting, created, summary)
        except Exception as exc:
            frappe.db.rollback()
            summary.errors.append("%s: %s" % (created.get("advice"), str(exc)))
            frappe.log_error(frappe.get_traceback(), "sf_trading: advice progression failed")
        else:
            frappe.db.commit()


def _advance_one(setting, created, summary):
    """Submit the advice, then optionally raise and submit its Payment Entry."""
    from vansale.sf_trading.doctype.payment_advice.payment_advice import create_payment_entry

    amount = flt(created.get("amount"))

    if flt(setting.submit_threshold) and amount > flt(setting.submit_threshold):
        summary.skipped.append(
            {
                "party": created.get("party"),
                "reason": "above_submit_threshold",
                "label": _("Left as draft — above the submit threshold"),
            }
        )
        return

    advice = frappe.get_doc("Payment Advice", created["advice"])
    advice.submit()
    summary.submitted_advices.append(created["advice"])

    if not cint(setting.auto_create_payment_entry):
        return

    submit_pe = cint(setting.auto_submit_payment_entry)
    if submit_pe and flt(setting.payment_entry_threshold) and amount > flt(
        setting.payment_entry_threshold
    ):
        submit_pe = 0
        summary.skipped.append(
            {
                "party": created.get("party"),
                "reason": "above_pe_threshold",
                "label": _("Payment Entry left as draft — above the threshold"),
            }
        )

    pe_name = create_payment_entry(created["advice"], submit=submit_pe)
    summary.payment_entries.append(pe_name)
    if submit_pe:
        summary.submitted_payment_entries.append(pe_name)


# ── notification ─────────────────────────────────────────────────────────────────

def _notify(setting, summary):
    """Tell the configured roles what happened, on the channels already in use."""
    created = len(summary.advices)
    nothing_happened = not (created or summary.errors)

    if nothing_happened and not cint(setting.notify_on_nothing_to_do):
        return

    users = _notify_users(setting)
    if not users:
        return

    if summary.dry_run:
        headline = _("Dry run: %(parties)s party(ies) would be paid") % {
            "parties": summary.get("considered") or 0
        }
    elif created:
        headline = _("%(count)s Payment Advice(s) raised — %(total)s") % {
            "count": created,
            "total": frappe.utils.fmt_money(summary.total_amount, precision=3),
        }
    else:
        headline = _("Payment automation ran with nothing to pay")

    detail = _summary_html(setting, summary)
    email_enabled = _outgoing_email_configured()

    for user in users:
        _push_realtime(user, headline, summary)
        _push_bell(user, headline)
        if email_enabled:
            _send_email(setting, user, headline, detail)


def _notify_users(setting):
    roles = setting.notify_role_names()
    if not roles:
        return []

    holders = frappe.get_all(
        "Has Role", filters={"role": ["in", roles], "parenttype": "User"}, pluck="parent"
    )
    if not holders:
        return []

    return [
        user
        for user in frappe.get_all(
            "User",
            filters={"name": ["in", holders], "enabled": 1, "user_type": "System User"},
            pluck="name",
        )
        if user not in ("Administrator", "Guest")
    ]


def _push_realtime(user, headline, summary):
    try:
        frappe.publish_realtime(
            event=ALERT_EVENT,
            message={
                "title": _("Payment automation"),
                "message": headline,
                "count": len(summary.advices),
                "outstanding": flt(summary.total_amount),
                "report": NOTIFICATION_REPORT,
            },
            user=user,
            after_commit=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sf_trading: automation realtime push failed")


def _push_bell(user, headline):
    try:
        from frappe.desk.doctype.notification_log.notification_log import (
            enqueue_create_notification,
        )

        enqueue_create_notification(
            [user],
            {
                "type": "Alert",
                "subject": headline,
                "document_type": "Payment Advice",
                "link": "/app/payment-advice?auto_generated=1",
                "from_user": frappe.session.user or "Administrator",
            },
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sf_trading: automation bell notification failed")


def _outgoing_email_configured():
    return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1}))


def _send_email(setting, user, headline, detail):
    """Best effort, exactly like the overdue digest: no outgoing account, no email, no error."""
    from frappe.desk.doctype.notification_settings.notification_settings import (
        is_email_notifications_enabled,
        is_notifications_enabled,
    )

    if not is_notifications_enabled(user) or not is_email_notifications_enabled(user):
        return

    recipient = frappe.db.get_value("User", user, "email") or user
    if not recipient:
        return

    message = detail
    if setting.email_template:
        try:
            template = frappe.get_doc("Email Template", setting.email_template)
            message = frappe.render_template(
                template.response_html or template.response or detail,
                {"doc": setting, "summary": setting.as_dict(), "headline": headline, "detail": detail},
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "sf_trading: automation email template failed")

    try:
        frappe.sendmail(
            recipients=[recipient],
            subject=headline,
            message=message,
            reference_doctype="Payment Automation Settings",
            reference_name=setting.name,
        )
    except frappe.OutgoingEmailError:
        return
    except Exception:
        frappe.log_error(frappe.get_traceback(), "sf_trading: automation email failed")


def _summary_html(setting, summary):
    def rows(items, render):
        return "".join("<li>%s</li>" % render(i) for i in items) or "<li>%s</li>" % _("None")

    parts = [
        "<p><b>", frappe.utils.escape_html(setting.name), "</b>",
        " — ", frappe.utils.escape_html(setting.company), "</p>",
        "<p>", _("Advices created"), ": <b>", str(len(summary.advices)), "</b>",
        " · ", _("submitted"), ": ", str(len(summary.submitted_advices)),
        " · ", _("Payment Entries"), ": ", str(len(summary.payment_entries)),
        " · ", _("submitted"), ": ", str(len(summary.submitted_payment_entries)), "</p>",
        "<p>", _("Total"), ": <b>",
        frappe.utils.escape_html(frappe.utils.fmt_money(summary.total_amount, precision=3)),
        "</b></p>",
        "<p>", _("Advices"), ":</p><ul>",
        rows(summary.advices, lambda a: "%s — %s — %s" % (
            frappe.utils.escape_html(a.get("advice") or ""),
            frappe.utils.escape_html(a.get("party") or ""),
            frappe.utils.fmt_money(flt(a.get("amount")), precision=3),
        )),
        "</ul>",
        "<p>", _("Skipped"), ":</p><ul>",
        rows(summary.skipped, lambda s: "%s — %s" % (
            frappe.utils.escape_html(s.get("party") or ""),
            frappe.utils.escape_html(s.get("label") or s.get("reason") or ""),
        )),
        "</ul>",
    ]

    if summary.errors:
        parts += ["<p>", _("Errors"), ":</p><ul>",
                  rows(summary.errors, lambda e: frappe.utils.escape_html(str(e))), "</ul>"]

    return "".join(parts)


# ── manual trigger ───────────────────────────────────────────────────────────────

@frappe.whitelist()
def run_now(settings_name: str, dry_run: int = 0):
    """Run a configuration immediately from its form, ignoring the schedule window."""
    setting = frappe.get_doc("Payment Automation Settings", settings_name)
    setting.check_permission("write")

    # a one-off dry run is passed through, never persisted on the configuration
    return run_automation(settings_name, force=1, dry_run=cint(dry_run) or None)
