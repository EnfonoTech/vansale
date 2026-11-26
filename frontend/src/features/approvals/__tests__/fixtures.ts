/** Builders for the approvals tests: one valid object each, overridden per test. */
import type { ActionFlag, ActionSpec, ApprovalItem, Inbox } from "@/api/approvals";

export function flag(action: string, over: Partial<ActionFlag> = {}): ActionFlag {
  return {
    action,
    require_comment: false,
    require_attachment: false,
    is_return_for_correction: false,
    ...over,
  };
}

export function spec(over: Partial<ActionSpec> = {}): ActionSpec {
  return {
    action: "Approve",
    next_state: "Approved",
    tone: "approve",
    require_comment: false,
    require_attachment: false,
    is_return_for_correction: false,
    priority: "Medium",
    recommend_only: false,
    ...over,
  };
}

export function item(over: Partial<ApprovalItem> = {}): ApprovalItem {
  return {
    action_id: "PMWA-0001",
    doctype: "Journal Entry",
    docname: "ACC-JV-2026-00001",
    transaction: "Journal Entry",
    area: "Accounts",
    party: "Al Noor Trading",
    amount: 1250.5,
    currency: "BHD",
    priority: "Medium",
    state: "Pending Approval",
    role_id: "Accounts Manager",
    days: 3,
    creator: "Fatima Hassan",
    created: "2026-11-16T09:30:00",
    category: "Approval Pending",
    is_adhoc: false,
    forwarded_by: "",
    return_to_originator: false,
    is_waiting: false,
    waiting_with: "",
    available_actions: [flag("Approve"), flag("Reject", { require_comment: true })],
    ...over,
  };
}

export function inbox(over: Partial<Inbox> = {}): Inbox {
  const first = item();
  return {
    total: 1,
    needs_you: 1,
    waiting: 0,
    stats: { high: 0, overdue: 0 },
    sections: [{ category: "Approval Pending", items: [first] }],
    waiting_items: [],
    fetched_at: "2026-11-19T08:00:00Z",
    ...over,
  };
}
