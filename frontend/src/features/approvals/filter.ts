import type { ApprovalItem } from "@/api/approvals";

export interface ItemFilter {
  /** An area chip, or "All". */
  area: string;
  /** Free text; empty keeps everything. */
  query: string;
}

/** How the To approve list is ordered: Permission Manager's own order (urgency first), or by when each document arrived. */
export type SortMode = "priority" | "newest" | "oldest";

export const SORT_MODES: readonly SortMode[] = ["priority", "newest", "oldest"];

const DAY_MS = 86_400_000;

/** When the item reached the user, in ms: its `created` stamp, else "now minus its age in days" (a day's precision is all that is known). */
function arrivedMs(item: ApprovalItem, now: number): number {
  const parsed = item.created ? Date.parse(item.created) : Number.NaN;
  return Number.isNaN(parsed) ? now - (item.days || 0) * DAY_MS : parsed;
}

/**
 * The items ordered by arrival, newest or oldest first; "priority" keeps the
 * order given (the server's). Items that arrived at the same moment keep their
 * given order. The input is not changed.
 */
export function sortItems(items: ApprovalItem[], mode: SortMode, now: number = Date.now()): ApprovalItem[] {
  if (mode === "priority") return items;
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
    if (!needle) return true;
    return [item.docname, item.party, item.transaction, item.creator].some((text) =>
      (text || "").toLowerCase().includes(needle),
    );
  });
}
