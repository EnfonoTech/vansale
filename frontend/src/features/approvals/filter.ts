import type { ApprovalItem } from "@/api/approvals";

export interface ItemFilter {
  /** An area chip, or "All". */
  area: string;
  /** Free text; empty keeps everything. */
  query: string;
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
