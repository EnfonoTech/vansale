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
 * Why `candidate` may not join `selected`, as an i18n key, or null when it may.
 * A document already selected is never blocked (it must stay deselectable).
 */
export function blockedReason(
  selected: ApprovalItem[],
  candidate: ApprovalItem,
  max: number = BULK_MAX,
): string | null {
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

const REJECT_WORDS = /reject|return|send back|decline|deny|refuse|cancel|revoke/i;
const APPROVE_WORDS = /approve|accept|authori[sz]e|confirm|verify|acknowledge|complete|submit/i;

/** How a bulk button is styled: PM's action labels carry no tone, so it is read from the label. */
export function actionTone(flag: ActionFlag): ActionTone {
  if (flag.is_return_for_correction || REJECT_WORDS.test(flag.action)) return "reject";
  if (APPROVE_WORDS.test(flag.action)) return "approve";
  return "other";
}

/** The server's UTC stamp as a Date, or null when there is none or it is unreadable. */
export function parseServerTime(stamp: string | null | undefined): Date | null {
  if (!stamp) return null;
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * The user has no van app (neither Van User nor Van Manager: the session's
 * `hasVanShell`), so the app is Approvals and More only and no van endpoint is
 * called for them. Unknown until the user's settings have loaded (`defaults`
 * is null): nobody is moved by a guess.
 */
export function approvalsOnly(session: { defaults: unknown; hasVanShell: boolean }): boolean {
  return session.defaults != null && !session.hasVanShell;
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
