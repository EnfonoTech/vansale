/**
 * Display and flow helpers for the three list tabs (My requests, Sent back,
 * History) and the bulk confirm sheet. Pure: no Vue, no Pinia, no i18n; the
 * screens pass the words through `t()`.
 */
import type { ApprovalItem, BulkRow, HistoryRow } from "@/api/approvals";

/** The most documents one bulk batch may hold (the server refuses more). */
export const BULK_LIMIT = 20;

// ─── How long ───────────────────────────────────────────────────────────────

/** The part of an i18n key that says how long: "today", or a plural category of the language. */
export type AgeKey = "today" | "one" | "two" | "few" | "many" | "other";

/**
 * How `days` is worded. Arabic has six plural forms, which a two-way
 * singular/plural pipe cannot give, so the locale's own plural rules choose.
 */
export function ageKey(days: number, locale: string): AgeKey {
  if (!(days > 0)) return "today";
  let category: Intl.LDMLPluralRule;
  try {
    category = new Intl.PluralRules(locale || "en").select(days);
  } catch {
    category = "other";
  }
  // "zero" only comes for 0, which is "today" above.
  return category === "zero" ? "other" : category;
}

// ─── Bulk sheet ─────────────────────────────────────────────────────────────

export interface Money {
  /** ISO currency code. */
  code: string;
  total: number;
}

/**
 * The batch's total, one line per currency (a batch rarely mixes them, but
 * the server does not promise it). A document with no readable amount adds
 * nothing and is counted in `unknown`, so the screen can say the total
 * leaves it out. `fallback` stands in for a document with no currency.
 */
export function bulkTotals(items: ApprovalItem[], fallback: string): { totals: Money[]; unknown: number } {
  const sums = new Map<string, number>();
  let unknown = 0;
  for (const item of items) {
    if (item.amount === null || item.amount === undefined || Number.isNaN(Number(item.amount))) {
      unknown += 1;
      continue;
    }
    const code = item.currency || fallback;
    sums.set(code, (sums.get(code) ?? 0) + Number(item.amount));
  }
  const totals = [...sums].map(([code, total]) => ({ code, total: Math.round(total * 1e6) / 1e6 }));
  return { totals, unknown };
}

/** What the batch shows for one document: waiting, done, or refused (with the server's words). */
export type RowState = { kind: "idle" } | { kind: "ok" } | { kind: "failed"; message: string };

/** The state of each of `names` after the answers `rows`; a document without an answer is idle. */
export function rowStates(names: string[], rows: BulkRow[]): Map<string, RowState> {
  const byName = new Map(rows.map((row) => [row.docname, row]));
  const out = new Map<string, RowState>();
  for (const name of names) {
    const row = byName.get(name);
    if (!row) out.set(name, { kind: "idle" });
    else out.set(name, row.ok ? { kind: "ok" } : { kind: "failed", message: row.message });
  }
  return out;
}

/** The documents to send again: refused ones, and any the server did not answer for. */
export function retryNames(names: string[], rows: BulkRow[]): string[] {
  const states = rowStates(names, rows);
  return names.filter((name) => states.get(name)?.kind !== "ok");
}

/** The earlier answers with the newer ones laid over them (a retry replaces a document's row). */
export function mergeResults(previous: BulkRow[], latest: BulkRow[]): BulkRow[] {
  const latestByName = new Map(latest.map((row) => [row.docname, row]));
  const merged = previous.map((row) => latestByName.get(row.docname) ?? row);
  const seen = new Set(previous.map((row) => row.docname));
  for (const row of latest) if (!seen.has(row.docname)) merged.push(row);
  return merged;
}

/** What the sheet may do after a request failed: ask again, or only close and look. */
export type BulkFailureState = "retry" | "unknown";

/**
 * A failed request is not a refusal. The server decides and commits the
 * documents one by one while the phone waits, so once the request has gone out
 * and no answer came back (the connection dropped, the wait ran out) some or all
 * of the batch may already be decided, and asking again could decide a
 * document twice (for a user who holds two steps in a row). So after a send
 * the result is unknown and nothing may be sent again until the inbox has been
 * reloaded; only before anything left the phone is asking again safe.
 */
export function bulkStateAfterFailure(sent: boolean): BulkFailureState {
  return sent ? "unknown" : "retry";
}

// ─── Sent back ──────────────────────────────────────────────────────────────

export type SentBackTarget =
  | { kind: "route"; location: { name: string; params: { name: string } } }
  | { kind: "desk"; url: string };

/** The app's own edit screen for the documents it can edit. */
const EDIT_ROUTE: Record<string, string> = {
  Quotation: "quotation-edit",
  "Sales Order": "order-edit",
  "Sales Invoice": "invoice-edit",
};

/** `url` when it is a path on this site or an http(s) address; "" otherwise (never a script). */
export function safeDeskUrl(url: string): string {
  const text = (url || "").trim();
  if (/^\/(?!\/)/.test(text)) return text;
  return /^https?:\/\//i.test(text) ? text : "";
}

/**
 * The mark Permission Manager puts on the filter value of a document that is
 * a return: `"Sales Invoice::1"` (and `::0` when it is not). It is the one
 * thing on a row that does not depend on the user's language: the label
 * (`transaction`) is translated, so "Sales Invoice" is not what an Arabic
 * user's ordinary invoice says.
 */
const RETURN_MARK = "::1";

/**
 * Where "Open and correct" goes. Quotation, Sales Order and Sales Invoice open
 * the app's own edit screen; everything else opens the desk form. Two cases
 * go to the desk form too: a return (a Sales Invoice that Permission Manager
 * marks as one in `transaction_filter`), which has no editor in the app, and
 * any document when the user has no van app, because the edit screens are van
 * screens and the router would send that user back to Approvals without a word.
 */
export function sentBackTarget(
  row: {
    doctype: string;
    docname: string;
    transaction_filter: string;
    doc_url: string;
  },
  hasVanShell: boolean,
): SentBackTarget {
  const route = EDIT_ROUTE[row.doctype];
  const isReturn = row.doctype === "Sales Invoice" && (row.transaction_filter || "").endsWith(RETURN_MARK);
  if (route && !isReturn && hasVanShell) {
    return { kind: "route", location: { name: route, params: { name: row.docname } } };
  }
  return { kind: "desk", url: safeDeskUrl(row.doc_url) };
}

// ─── History ────────────────────────────────────────────────────────────────

export interface TransactionOption {
  /** What the server filters by (a row's `transaction_filter`). */
  value: string;
  /** What the person reads (a row's `transaction`). */
  label: string;
}

/**
 * The transaction filter's choices: the ones already known plus any new in
 * `rows`, by label. They accumulate, because once a filter is chosen the
 * rows hold only that one and the others would vanish from the list.
 */
export function mergeTransactions(
  known: TransactionOption[],
  rows: Pick<HistoryRow, "transaction" | "transaction_filter">[],
): TransactionOption[] {
  const byValue = new Map(known.map((option) => [option.value, option]));
  for (const row of rows) {
    const value = row.transaction_filter || row.transaction;
    if (value && !byValue.has(value)) byValue.set(value, { value, label: row.transaction || value });
  }
  return [...byValue.values()].sort((a, b) => a.label.localeCompare(b.label));
}

/** True when both dates are given and the range runs backwards (YYYY-MM-DD sorts as text). */
export function dateRangeReversed(from: string, to: string): boolean {
  return !!from && !!to && from > to;
}
