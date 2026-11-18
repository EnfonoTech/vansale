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
