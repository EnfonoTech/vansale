/**
 * Customer names on invoices, payments and returns: the customer's title
 * (Badria: English name) first, and the name the document stored (Badria:
 * Arabic) as well when the two differ.
 */

/** The stored name, when it differs from the title; else "". */
export function otherCustomerName(title?: string | null, name?: string | null): string {
  const t = (title || "").trim();
  const n = (name || "").trim();
  return t && n && t.toLowerCase() !== n.toLowerCase() ? n : "";
}

/** One line: "fgh (sad522)", or just the name when there is only one. */
export function customerLine(title?: unknown, name?: unknown, id?: unknown): string {
  const text = (v: unknown) => (v == null ? "" : String(v));
  const main = (text(title) || text(name) || text(id)).trim();
  const other = otherCustomerName(text(title), text(name) || text(id));
  return other ? `${main} (${other})` : main;
}
