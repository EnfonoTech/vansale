/**
 * Approvals: the documents waiting on the signed-in user (Permission Manager
 * workflows), their review and the decision on them. Endpoints live in
 * `vansale.steelforce.approvals` (forward, attach and the list tabs in
 * `vansale.steelforce.approvals_extra`); on a site without Permission Manager
 * they answer "nothing here" and the screens stay hidden (`availability`).
 *
 * The types below follow what the server returns, not what the screens would
 * like it to. Approvals need a connection: none of these calls is queued
 * offline.
 */
import { apiCall } from "./client";

/** Inbox, review and decision. */
const BASE = "vansale.steelforce.approvals";
/** Forward, attach and the three list tabs (a separate server module). */
const EXTRA = "vansale.steelforce.approvals_extra";

// ─── Inbox ──────────────────────────────────────────────────────────────────

export type Priority = "Low" | "Medium" | "High" | "Critical";

/** The filter chip a document type belongs to. */
export type Area = "Accounts" | "Purchase" | "Sales" | "Masters" | "Stock" | "Other";

/** What one action asks for in the document's current state. */
export interface ActionFlag {
  action: string;
  require_comment: boolean;
  require_attachment: boolean;
  is_return_for_correction: boolean;
}

export interface ApprovalItem {
  /** The PM Workflow Action's name; forwarding needs it. */
  action_id: string;
  doctype: string;
  docname: string;
  /** Permission Manager's label, e.g. "Sales Return". */
  transaction: string;
  area: Area;
  party: string;
  /** null when the user may not read the amount (or the type has none): show no amount. */
  amount: number | null;
  /** "" when unknown: fall back to the session currency. */
  currency: string;
  priority: Priority;
  state: string;
  role_id: string;
  days: number;
  creator: string;
  /** Permission Manager's category, e.g. "Approval Pending"; "" when it gave none. */
  category: string;
  is_adhoc: boolean;
  /** Full name of who forwarded it to the user, or "". */
  forwarded_by: string;
  return_to_originator: boolean;
  /** Forwarded away or held by someone else: shown, with no buttons. */
  is_waiting: boolean;
  waiting_with: string;
  /** Static per state; a hint for bulk decisions, not a permission. */
  available_actions: ActionFlag[];
}

export interface InboxStats {
  high: number;
  overdue: number;
}

export interface InboxSection {
  category: string;
  items: ApprovalItem[];
}

export interface Inbox {
  /** Permission Manager's own total, the same number as the desk. */
  total: number;
  needs_you: number;
  waiting: number;
  /** Counted over the items that need the user. */
  stats: InboxStats;
  sections: InboxSection[];
  waiting_items: ApprovalItem[];
  /** UTC ISO time the server built it. */
  fetched_at: string;
}

/** The numbers alone, for badges. */
export interface ApprovalCount extends InboxStats {
  total: number;
  needs_you: number;
  waiting: number;
}

// ─── One document ───────────────────────────────────────────────────────────

export type ActionTone = "approve" | "reject" | "other";

export interface ActionSpec {
  action: string;
  next_state: string;
  tone: ActionTone;
  require_comment: boolean;
  require_attachment: boolean;
  is_return_for_correction: boolean;
  priority: string;
  /** The user was asked for advice: the document will not move. */
  recommend_only: boolean;
}

export interface DetailFact {
  label: string;
  value: string;
}

export interface DetailLines {
  columns: string[];
  rows: string[][];
  /** All the document's lines; `rows` holds only the first few. */
  total: number;
}

export interface DetailAttachment {
  name: string;
  url: string;
  is_private: boolean;
}

export interface DetailComment {
  by: string;
  when: string;
  text: string;
}

/** Permission Manager's document lifecycle. */
export interface RouteStep {
  state: string;
  status: "done" | "current" | "upcoming";
  roles: string[];
  by: string;
  final: boolean;
}

export interface RouteRole {
  role: string;
  users: { user: string; full_name: string }[];
  count: number;
}

export interface RouteEvent {
  by: string;
  user: string;
  state: string;
  to_state: string;
  action: string;
  on: string;
}

export interface Route {
  chain: RouteStep[];
  roles: RouteRole[];
  events: RouteEvent[];
  current: string;
  finished: boolean;
}

export type Banner =
  | { kind: "recommend"; forwarder: string }
  | { kind: "waiting"; holder: string }
  | { kind: "self_owned" }
  | { kind: "cannot_read" };

export interface Detail {
  doctype: string;
  docname: string;
  transaction: string;
  state: string;
  priority: string;
  party: string;
  /** null when unreadable or hidden: show no amount. */
  amount: number | null;
  /** "" when unknown: fall back to the session currency. */
  currency: string;
  creator: string;
  facts: DetailFact[];
  lines: DetailLines;
  attachments: DetailAttachment[];
  has_attachment: boolean;
  comments: DetailComment[];
  route: Route;
  actions: ActionSpec[];
  /** The user's open approval on it; null when they hold none. */
  action_id: string | null;
  banner: Banner | null;
  can_forward: boolean;
  desk_url: string;
}

export interface ApplyResult {
  ok: boolean;
  new_state: string;
  /** True when the user was asked for advice and the document did not move. */
  recommended: boolean;
}

export interface BulkRow {
  docname: string;
  ok: boolean;
  /** The refusal as it was raised; "" on success. */
  message: string;
}

export interface BulkResult {
  results: BulkRow[];
  ok_count: number;
  failed_count: number;
}

// ─── Forward, attach ────────────────────────────────────────────────────────

export interface ForwardTarget {
  user: string;
  full_name: string;
  role: string;
}

export interface ForwardResult {
  adhoc_action: string;
  return_to_originator: number;
}

export interface AttachResult {
  name: string;
  url: string;
}

// ─── Other tabs ─────────────────────────────────────────────────────────────

/** A document the user submitted that is still moving through approval. */
export interface MyRequestRow {
  doctype: string;
  docname: string;
  transaction: string;
  state: string;
  holder: string;
  role_id: string;
  days: number;
  priority: string;
}

/** A document sent back to the user for correction (Permission Manager's row). */
export interface SentBackRow {
  doctype: string;
  transaction: string;
  transaction_filter: string;
  docname: string;
  state: string;
  submitted_by: string;
  days: number;
  doc_url: string;
  sent_back_by: string;
  sent_back_on: string;
  role: string;
  reason: string;
}

/** A decision the user took (Permission Manager's row). */
export interface HistoryRow {
  name: string;
  doctype: string;
  transaction: string;
  transaction_filter: string;
  docname: string;
  action_state: string;
  current_state: string;
  role: string;
  completed_by: string;
  date: string;
  doc_url: string;
  event_count: number;
  submitted_by?: string;
}

// ─── Calls ──────────────────────────────────────────────────────────────────

/** `?a=1&b=2` for a GET; empty values are left out. */
function query(params: Record<string, string | number>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== "") qs.set(key, String(value));
  }
  return qs.toString();
}

export function availability(): Promise<{ enabled: boolean }> {
  return apiCall("GET", `${BASE}.availability`);
}

export function inbox(): Promise<Inbox> {
  return apiCall("GET", `${BASE}.inbox`);
}

export function count(): Promise<ApprovalCount> {
  return apiCall("GET", `${BASE}.count`);
}

export function detail(doctype: string, name: string): Promise<Detail> {
  return apiCall("GET", `${BASE}.detail?${query({ doctype, name })}`);
}

/**
 * Take `action` on one document. A refusal is thrown as the server worded it.
 *
 * `priority` is "" when the approver has not chosen one: the server then lets
 * the transition's own default apply (the client never sends a made-up one).
 * `expectedState` is the document's workflow state when the approver opened
 * it (`Detail.state`); the server refuses with "changed since you opened it"
 * when the document has moved on. "" means no check.
 */
export function apply(
  doctype: string,
  name: string,
  action: string,
  comment = "",
  priority = "",
  expectedState = "",
): Promise<ApplyResult> {
  return apiCall("POST", `${BASE}.apply`, {
    doctype,
    name,
    action,
    comment,
    priority,
    expected_state: expectedState,
  });
}

/**
 * How long a bulk decision may take. The server decides and commits the
 * documents one by one (up to 20, one to three seconds each), so the client's
 * usual 20 s would give up on a request that is still working.
 */
export const BULK_TIMEOUT_MS = 120_000;

/**
 * Take `action` on up to 20 documents of one type; each succeeds or fails alone.
 *
 * `priority` "" = not chosen (the transition's own default applies).
 * `expectedStates` maps a document name to its workflow state when it was
 * listed; a document that has moved on since gets a failed row ("changed
 * since you opened it") and is not decided. A name missing from the map is
 * not checked.
 */
export function applyBulk(
  doctype: string,
  names: string[],
  action: string,
  comment = "",
  priority = "",
  expectedStates: Record<string, string> = {},
): Promise<BulkResult> {
  // The server reads `names` and `expected_states` as JSON strings.
  return apiCall(
    "POST",
    `${BASE}.apply_bulk`,
    {
      doctype,
      names: JSON.stringify(names),
      action,
      comment,
      priority,
      expected_states: Object.keys(expectedStates).length ? JSON.stringify(expectedStates) : "",
    },
    BULK_TIMEOUT_MS,
  );
}

/** Users the document can be forwarded to (at most 20), narrowed by what was typed. */
export function forwardTargets(doctype: string, name: string, text = ""): Promise<ForwardTarget[]> {
  return apiCall("GET", `${EXTRA}.forward_targets?${query({ doctype, name, query: text })}`);
}

export function forward(
  actionId: string,
  toUser: string,
  comment = "",
  returnToOriginator: boolean | number = false,
): Promise<ForwardResult> {
  return apiCall("POST", `${EXTRA}.forward`, {
    action_id: actionId,
    to_user: toUser,
    comment,
    return_to_originator: returnToOriginator ? 1 : 0,
  });
}

/** Hand a "return to me" forward back to whoever asked for the user's advice. */
export function returnToOriginator(actionId: string, comment = ""): Promise<Record<string, unknown>> {
  return apiCall("POST", `${EXTRA}.return_to_originator`, { action_id: actionId, comment });
}

/** Attach a file (base64, no data-URL prefix) to the document. */
export function attach(
  doctype: string,
  name: string,
  filename: string,
  contentBase64: string,
): Promise<AttachResult> {
  return apiCall("POST", `${EXTRA}.attach`, {
    doctype,
    name,
    filename,
    content_base64: contentBase64,
  });
}

export function myRequests(): Promise<{ items: MyRequestRow[] }> {
  return apiCall("GET", `${EXTRA}.my_requests`);
}

export function sentBack(): Promise<{ items: SentBackRow[] }> {
  return apiCall("GET", `${EXTRA}.sent_back`);
}

export function history(
  limit = 100,
  fromDate = "",
  toDate = "",
  transaction = "",
): Promise<{ items: HistoryRow[] }> {
  const qs = query({ limit, from_date: fromDate, to_date: toDate, transaction });
  return apiCall("GET", `${EXTRA}.history?${qs}`);
}
