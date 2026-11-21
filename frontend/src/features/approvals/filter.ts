import type { ApprovalItem } from "@/api/approvals";

/** "Overdue" means waiting more than this many days. */
export const OVERDUE_DAYS = 30;

/** The stat the user tapped: everything, only High and Critical, or only the overdue ones. */
export type QuickFilter = "all" | "high" | "overdue";

export interface ItemFilter {
  /** An area chip, or "All". */
  area: string;
  /** Free text; empty keeps everything. */
  query: string;
  /** A tapped stat; missing means everything. */
  quick?: QuickFilter;
}

function passesQuick(item: ApprovalItem, quick: QuickFilter | undefined): boolean {
  if (quick === "high") return item.priority === "High" || item.priority === "Critical";
  if (quick === "overdue") return item.days > OVERDUE_DAYS;
  return true;
}

/** How the To approve list is ordered: Permission Manager's own order (urgency first), by when each document arrived, or by amount. */
export type SortMode = "priority" | "newest" | "oldest" | "amount";

export const SORT_MODES: readonly SortMode[] = ["priority", "newest", "oldest", "amount"];

const DAY_MS = 86_400_000;

/** When the item reached the user, in ms: its `created` stamp, else "now minus its age in days" (a day's precision is all that is known). */
function arrivedMs(item: ApprovalItem, now: number): number {
  const parsed = item.created ? Date.parse(item.created) : Number.NaN;
  return Number.isNaN(parsed) ? now - (item.days || 0) * DAY_MS : parsed;
}

/**
 * The items ordered by arrival (newest or oldest first) or by amount (largest
 * first, documents with no amount last); "priority" keeps the order given (the
 * server's). Items that tie keep their given order. The input is not changed.
 */
export function sortItems(items: ApprovalItem[], mode: SortMode, now: number = Date.now()): ApprovalItem[] {
  if (mode === "priority") return items;
  if (mode === "amount") {
    return items
      .map((item, index) => ({ item, index, value: typeof item.amount === "number" ? item.amount : null }))
      .sort((a, b) => {
        if (a.value === null || b.value === null) return Number(a.value === null) - Number(b.value === null) || a.index - b.index;
        return b.value - a.value || a.index - b.index;
      })
      .map((entry) => entry.item);
  }
  const sign = mode === "newest" ? -1 : 1;
  return items
    .map((item, index) => ({ item, index, at: arrivedMs(item, now) }))
    .sort((a, b) => sign * (a.at - b.at) || a.index - b.index)
    .map((entry) => entry.item);
}

/** The items in the chosen area whose document, party, transaction or creator contains the text. */
export function filterItems(items: ApprovalItem[], q: ItemFilter): ApprovalItem[] {
  const needle = q.query.trim().toLowerCase();
  return items.filter((item) => {
    if (q.area !== "All" && item.area !== q.area) return false;
    if (!passesQuick(item, q.quick)) return false;
    if (!needle) return true;
    return [item.docname, item.party, item.transaction, item.creator].some((text) =>
      (text || "").toLowerCase().includes(needle),
    );
  });
}
