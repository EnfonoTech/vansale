/**
 * What the To approve tab works out from the inbox: which items its filters
 * keep, how many each area chip holds, which documents may join a bulk
 * selection and what a bulk action looks like. Pure: no Vue, no Pinia.
 *
 * Who may decide what stays Permission Manager's business; `bulkShared` (in
 * `rules.ts`) is the client's early hint and the server checks every document
 * again when the batch is applied.
 */
import type { ActionFlag, ActionTone, ApprovalItem, InboxSection } from "@/api/approvals";
import { filterItems, type ItemFilter } from "./filter";
import { bulkShared } from "./rules";

/** Most documents one batch may hold (the server refuses more). */
export const BULK_MAX = 20;
/** "Overdue" means more than this many days. */
export const OVERDUE_DAYS = 30;

/** i18n keys of why a document cannot join the selection (the mixed-types key is `BULK_MIXED_TYPES`). */
export const NO_SHARED_REASON = "approvalsInbox.selection.noShared";
export const LIMIT_REASON = "approvalsInbox.selection.limit";
export const REVIEW_ONLY_REASON = "approvalsInbox.selection.reviewOnly";
export const ADVICE_ONLY_REASON = "approvalsInbox.selection.adviceOnly";

/** A document's identity in a list: names repeat across types. */
export function itemKey(item: Pick<ApprovalItem, "doctype" | "docname">): string {
  return `${item.doctype}::${item.docname}`;
}

export function isOverdue(days: number): boolean {
  return days > OVERDUE_DAYS;
}

/** The sections with only the items the filter keeps; a section left empty is dropped. Order is the server's. */
export function filterSections(sections: InboxSection[], filter: ItemFilter): InboxSection[] {
  const out: InboxSection[] = [];
  for (const section of sections) {
    const items = filterItems(section.items, filter);
    if (items.length) out.push({ category: section.category, items });
  }
  return out;
}

/** How many items each area holds, plus `All`. Areas with none are left out. */
export function areaCounts(items: ApprovalItem[]): Record<string, number> {
  const counts: Record<string, number> = { All: items.length };
  for (const item of items) counts[item.area] = (counts[item.area] ?? 0) + 1;
  return counts;
}

/**
 * The document was forwarded to the user with "return to me": they are asked
 * for advice, and whatever they press is recorded as a recommendation while
 * the document does not move (the server makes every action `recommend_only`
 * for them). A batch must never offer that as a decision, so such a document
 * is answered one at a time, from its own screen. A document the user
 * forwarded away (`is_waiting`) is not theirs to answer at all.
 */
export function isAdviceOnly(item: Pick<ApprovalItem, "is_adhoc" | "return_to_originator" | "is_waiting">): boolean {
  return Boolean(item.is_adhoc && item.return_to_originator && !item.is_waiting);
}

/**
 * Why `candidate` may not join `selected`, as an i18n key, or null when it may.
 * A document already selected is never blocked (it must stay deselectable).
 */
export function blockedReason(
  selected: ApprovalItem[],
  candidate: ApprovalItem,
  max: number = BULK_MAX,
): string | null {
  // Advice is not a decision: it is given from the document's own screen.
  if (isAdviceOnly(candidate)) return ADVICE_ONLY_REASON;
  // A document that no bulk action can take (every action wants a file) is decided from its own screen.
  if (bulkShared([candidate]).actions.length === 0) return REVIEW_ONLY_REASON;
  if (!selected.length) return null;

  const key = itemKey(candidate);
  if (selected.some((item) => itemKey(item) === key)) return null;
  if (selected.length >= max) return LIMIT_REASON;

  const shared = bulkShared([...selected, candidate]);
  if (shared.reason) return shared.reason;
  if (shared.actions.length === 0) return NO_SHARED_REASON;
  return null;
}

/**
 * How an action button is styled: "reject", "other" or "approve". The same rule
 * as the server's `tone_of` (`approvals_rules.py`), so the bulk bar, the confirm
 * sheet and the detail screen agree: a return-for-correction action is always
 * a reject; otherwise the name decides from its START ("Reject Cancellation"
 * rejects, "Request Cancellation" is neither, "Approve Return" approves); the
 * rest approve. Words inside a name mean nothing: PM's labels are not prose.
 */
export function actionTone(flag: ActionFlag): ActionTone {
  if (flag.is_return_for_correction) return "reject";
  const name = (flag.action || "").trim().toLowerCase();
  if (name.startsWith("reject")) return "reject";
  if (name.startsWith("request")) return "other";
  return "approve";
}

/** The server's UTC stamp as a Date, or null when there is none or it is unreadable. */
export function parseServerTime(stamp: string | null | undefined): Date | null {
  if (!stamp) return null;
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * The app is Approvals and More only, and no van endpoint is called: the user
 * has no van app (neither Van User, Van Manager nor an assigned van: the
 * session's `hasVanShell`) AND the site has approvals for them
 * (`approvalsEnabled`). Without Permission Manager there would be nothing to
 * show in that shell, so nobody is moved into it: a site that does not have
 * approvals keeps the van shell for everyone. Unknown until the user's
 * settings have loaded (`defaults` is null): nobody is moved by a guess.
 */
export function approvalsOnly(session: {
  defaults: unknown;
  hasVanShell: boolean;
  approvalsEnabled: boolean;
}): boolean {
  return session.defaults != null && session.approvalsEnabled && !session.hasVanShell;
}

/** The screens a user without the van app may open; every other screen is a van screen. */
const WITHOUT_VAN = new Set(["approvals", "approval-detail", "more", "pin", "login", "setup"]);

/** Whether the route named `name` may be opened by a user without the van app. */
export function routeAllowedWithoutVan(name: string | symbol | null | undefined): boolean {
  return typeof name === "string" && WITHOUT_VAN.has(name);
}

/** The text function the screens pass in (`t` from vue-i18n), so wording stays in the language files. */
export type Translate = (key: string, named?: Record<string, unknown>) => string;

/** How long an item has waited: "Today", "1 day", "7 days", in the user's language. */
export function ageText(days: number, t: Translate): string {
  if (!(days > 0)) return t("approvalsInbox.age.today");
  if (days === 1) return t("approvalsInbox.age.one");
  return t("approvalsInbox.age.many", { count: days });
}

/** An amount with the company's decimals (BHD 3, SAR 2), grouped the way the phone's language groups digits. */
export function formatAmount(value: number, precision: number, locale?: string): string {
  return new Intl.NumberFormat(locale, { minimumFractionDigits: precision, maximumFractionDigits: precision }).format(
    Number(value) || 0,
  );
}

/** A moment in the phone's clock and the app's language: "19 Nov 2026, 11:30". */
export function formatStamp(when: Date, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(when);
}
