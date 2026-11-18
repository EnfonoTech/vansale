import { describe, expect, it } from "vitest";
import {
  ageKey,
  bulkTotals,
  dateRangeReversed,
  expectedStatesOf,
  mergeResults,
  bulkStateAfterFailure,
  mergeTransactions,
  retryNames,
  rowStates,
  safeDeskUrl,
  sentBackTarget,
} from "../lists";
import { item } from "./fixtures";

describe("ageKey", () => {
  it("is today for 0 and for anything that is not a positive number", () => {
    expect(ageKey(0, "en")).toBe("today");
    expect(ageKey(-3, "en")).toBe("today");
    expect(ageKey(Number.NaN, "en")).toBe("today");
  });

  it("English has one and other", () => {
    expect(ageKey(1, "en")).toBe("one");
    expect(ageKey(2, "en")).toBe("other");
    expect(ageKey(30, "en")).toBe("other");
  });

  it("Arabic has its six forms (zero is today)", () => {
    expect(ageKey(1, "ar")).toBe("one");
    expect(ageKey(2, "ar")).toBe("two");
    expect(ageKey(3, "ar")).toBe("few");
    expect(ageKey(10, "ar")).toBe("few");
    expect(ageKey(11, "ar")).toBe("many");
    expect(ageKey(99, "ar")).toBe("many");
    expect(ageKey(100, "ar")).toBe("other");
  });

  it("an unknown locale falls back to English rules", () => {
    expect(ageKey(1, "")).toBe("one");
    expect(ageKey(5, "not a locale")).toBe("other");
  });
});

describe("bulkTotals", () => {
  it("adds the amounts of one currency", () => {
    const items = [
      item({ amount: 1200, currency: "BHD" }),
      item({ amount: 310.5, currency: "BHD" }),
      item({ amount: 88, currency: "BHD" }),
    ];
    expect(bulkTotals(items, "SAR")).toEqual({ totals: [{ code: "BHD", total: 1598.5 }], unknown: 0 });
  });

  it("keeps floating point noise out of the total", () => {
    const items = [item({ amount: 0.1, currency: "BHD" }), item({ amount: 0.2, currency: "BHD" })];
    expect(bulkTotals(items, "SAR").totals).toEqual([{ code: "BHD", total: 0.3 }]);
  });

  it("falls back to the given currency, and keeps currencies apart", () => {
    const items = [
      item({ amount: 10, currency: "" }),
      item({ amount: 5, currency: "SAR" }),
      item({ amount: 1, currency: "BHD" }),
    ];
    const { totals } = bulkTotals(items, "SAR");
    expect(totals).toContainEqual({ code: "SAR", total: 15 });
    expect(totals).toContainEqual({ code: "BHD", total: 1 });
    expect(totals).toHaveLength(2);
  });

  it("counts a document with no amount instead of adding it", () => {
    const items = [item({ amount: 40, currency: "BHD" }), item({ amount: null, currency: "" })];
    expect(bulkTotals(items, "BHD")).toEqual({ totals: [{ code: "BHD", total: 40 }], unknown: 1 });
  });

  it("a zero amount is an amount", () => {
    expect(bulkTotals([item({ amount: 0, currency: "BHD" })], "BHD")).toEqual({
      totals: [{ code: "BHD", total: 0 }],
      unknown: 0,
    });
  });

  it("nothing to add gives no total", () => {
    expect(bulkTotals([], "BHD")).toEqual({ totals: [], unknown: 0 });
    expect(bulkTotals([item({ amount: null })], "BHD")).toEqual({ totals: [], unknown: 1 });
  });
});

describe("bulk results", () => {
  const rows = [
    { docname: "A", ok: true, message: "" },
    { docname: "B", ok: false, message: "Not allowed" },
  ];

  it("rowStates: done, refused with the server's words, or not answered", () => {
    const states = rowStates(["A", "B", "C"], rows);
    expect(states.get("A")).toEqual({ kind: "ok" });
    expect(states.get("B")).toEqual({ kind: "failed", message: "Not allowed" });
    expect(states.get("C")).toEqual({ kind: "idle" });
  });

  it("retryNames: everything that is not done, in the batch's order", () => {
    expect(retryNames(["C", "B", "A"], rows)).toEqual(["C", "B"]);
    expect(retryNames(["A"], rows)).toEqual([]);
    expect(retryNames(["A", "B"], [])).toEqual(["A", "B"]);
  });

  it("mergeResults: a retry replaces a row and leaves the others", () => {
    const merged = mergeResults(rows, [{ docname: "B", ok: true, message: "" }]);
    expect(merged).toEqual([
      { docname: "A", ok: true, message: "" },
      { docname: "B", ok: true, message: "" },
    ]);
  });

  it("mergeResults: a document answered for the first time is added", () => {
    const merged = mergeResults(rows, [{ docname: "C", ok: false, message: "x" }]);
    expect(merged.map((row) => row.docname)).toEqual(["A", "B", "C"]);
  });
});

describe("sentBackTarget", () => {
  const base = { docname: "DOC-1", transaction_filter: "", doc_url: "/app/doc-1" };

  it.each([
    ["Quotation", "quotation-edit"],
    ["Sales Order", "order-edit"],
    ["Sales Invoice", "invoice-edit"],
  ])("%s opens the app's own edit screen", (doctype, name) => {
    expect(sentBackTarget({ ...base, doctype, transaction_filter: doctype }, true)).toEqual({
      kind: "route",
      location: { name, params: { name: "DOC-1" } },
    });
  });

  it("every other type opens the desk form", () => {
    expect(sentBackTarget({ ...base, doctype: "Journal Entry", transaction_filter: "Journal Entry" }, true)).toEqual({
      kind: "desk",
      url: "/app/doc-1",
    });
  });

  it("a Sales Invoice that is a return has no editor in the app: desk form", () => {
    expect(sentBackTarget({ ...base, doctype: "Sales Invoice", transaction_filter: "Sales Invoice::1" }, true)).toEqual({
      kind: "desk",
      url: "/app/doc-1",
    });
  });

  it("an ordinary Sales Invoice is not a return, marked ::0 or bare", () => {
    for (const transaction_filter of ["Sales Invoice::0", "Sales Invoice", ""]) {
      expect(sentBackTarget({ ...base, doctype: "Sales Invoice", transaction_filter }, true).kind).toBe("route");
    }
  });

  it("the reader's language does not make an invoice a return: only the filter value says so", () => {
    // `transaction` is the translated label ("فاتورة مبيعات"); it is not even an input here.
    const arabicUser = { ...base, doctype: "Sales Invoice", transaction: "فاتورة مبيعات", transaction_filter: "Sales Invoice::0" };
    expect(sentBackTarget(arabicUser, true)).toEqual({
      kind: "route",
      location: { name: "invoice-edit", params: { name: "DOC-1" } },
    });
    const arabicReturn = { ...arabicUser, transaction: "مرتجع مبيعات", transaction_filter: "Sales Invoice::1" };
    expect(sentBackTarget(arabicReturn, true).kind).toBe("desk");
  });

  it("a user without the van app always gets the desk form, since the edit screens are van screens", () => {
    for (const doctype of ["Quotation", "Sales Order", "Sales Invoice"]) {
      expect(sentBackTarget({ ...base, doctype, transaction_filter: doctype }, false)).toEqual({
        kind: "desk",
        url: "/app/doc-1",
      });
    }
  });

  it("without the van app and without a usable desk address there is nothing to open", () => {
    expect(sentBackTarget({ ...base, doctype: "Quotation", doc_url: "" }, false)).toEqual({ kind: "desk", url: "" });
  });

  it("a desk address that is not a path or an http(s) address is dropped", () => {
    expect(sentBackTarget({ ...base, doctype: "Journal Entry", doc_url: "javascript:alert(1)" }, true)).toEqual({
      kind: "desk",
      url: "",
    });
  });
});

describe("bulkStateAfterFailure", () => {
  it("after a send with no answer the result is unknown: nothing is sent again", () => {
    expect(bulkStateAfterFailure(true)).toBe("unknown");
  });

  it("before anything left the phone, asking again is safe", () => {
    expect(bulkStateAfterFailure(false)).toBe("retry");
  });
});

describe("safeDeskUrl", () => {
  it("keeps a path on this site and an http(s) address", () => {
    expect(safeDeskUrl("/app/sales-order/SO-1")).toBe("/app/sales-order/SO-1");
    expect(safeDeskUrl(" https://erp.example.com/app/x ")).toBe("https://erp.example.com/app/x");
    expect(safeDeskUrl("http://erp.example.com/app/x")).toBe("http://erp.example.com/app/x");
  });

  it("drops anything else", () => {
    expect(safeDeskUrl("")).toBe("");
    expect(safeDeskUrl("//evil.example.com/x")).toBe("");
    expect(safeDeskUrl("javascript:alert(1)")).toBe("");
    expect(safeDeskUrl("data:text/html,x")).toBe("");
    expect(safeDeskUrl("app/x")).toBe("");
  });
});

describe("mergeTransactions", () => {
  it("lists each transaction once, by label, filter value first", () => {
    const out = mergeTransactions(
      [],
      [
        { transaction: "Sales Return", transaction_filter: "Sales Return" },
        { transaction: "Journal Entry", transaction_filter: "Journal Entry" },
        { transaction: "Journal Entry", transaction_filter: "Journal Entry" },
      ],
    );
    expect(out).toEqual([
      { value: "Journal Entry", label: "Journal Entry" },
      { value: "Sales Return", label: "Sales Return" },
    ]);
  });

  it("keeps the ones already known when the rows hold fewer", () => {
    const known = [
      { value: "Journal Entry", label: "Journal Entry" },
      { value: "Sales Return", label: "Sales Return" },
    ];
    const out = mergeTransactions(known, [{ transaction: "Journal Entry", transaction_filter: "Journal Entry" }]);
    expect(out).toEqual(known);
  });

  it("uses the label when a row has no filter value, and skips a row with neither", () => {
    const out = mergeTransactions(
      [],
      [
        { transaction: "Payment Entry", transaction_filter: "" },
        { transaction: "", transaction_filter: "" },
      ],
    );
    expect(out).toEqual([{ value: "Payment Entry", label: "Payment Entry" }]);
  });
});

describe("dateRangeReversed", () => {
  it("is true only when both dates are set and from is after to", () => {
    expect(dateRangeReversed("2026-11-10", "2026-11-01")).toBe(true);
    expect(dateRangeReversed("2026-11-01", "2026-11-10")).toBe(false);
    expect(dateRangeReversed("2026-11-01", "2026-11-01")).toBe(false);
    expect(dateRangeReversed("", "2026-11-01")).toBe(false);
    expect(dateRangeReversed("2026-11-01", "")).toBe(false);
  });
});

describe("expectedStatesOf", () => {
  const docs = [
    item({ docname: "JV-1", state: "Pending Approval" }),
    item({ docname: "JV-2", state: "Pending Finance" }),
    item({ docname: "JV-3", state: "" }),
  ];

  it("maps each name to the state it was listed in", () => {
    expect(expectedStatesOf(docs, ["JV-1", "JV-2"])).toEqual({
      "JV-1": "Pending Approval",
      "JV-2": "Pending Finance",
    });
  });

  it("covers only the names being sent (a retry sends the refused ones)", () => {
    expect(expectedStatesOf(docs, ["JV-2"])).toEqual({ "JV-2": "Pending Finance" });
  });

  it("leaves out a document with no state, so the server does not check it", () => {
    expect(expectedStatesOf(docs, ["JV-1", "JV-3"])).toEqual({ "JV-1": "Pending Approval" });
  });

  it("ignores a name that is not among the documents", () => {
    expect(expectedStatesOf(docs, ["JV-9"])).toEqual({});
  });
});
