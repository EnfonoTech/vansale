import { describe, expect, it } from "vitest";
import { filterItems, sortItems } from "../filter";
import { item } from "./fixtures";

const items = [
  item({ docname: "ACC-JV-1", area: "Accounts", party: "Al Noor Trading", transaction: "Journal Entry", creator: "Fatima Hassan" }),
  item({ docname: "PINV-7", doctype: "Purchase Invoice", area: "Purchase", party: "Gulf Steel Supply", transaction: "Purchase Invoice", creator: "Omar Khalid" }),
  item({ docname: "SINV-9", doctype: "Sales Invoice", area: "Sales", party: "Bahrain Builders", transaction: "Sales Return", creator: "Fatima Hassan" }),
];

describe("filterItems", () => {
  it("All with no query keeps everything, in order", () => {
    expect(filterItems(items, { area: "All", query: "" })).toEqual(items);
  });

  it("keeps only the chosen area", () => {
    expect(filterItems(items, { area: "Purchase", query: "" }).map((i) => i.docname)).toEqual(["PINV-7"]);
  });

  it("matches a lower-case party fragment", () => {
    expect(filterItems(items, { area: "All", query: "gulf st" }).map((i) => i.docname)).toEqual(["PINV-7"]);
  });

  it("matches docname, transaction and creator, ignoring case", () => {
    expect(filterItems(items, { area: "All", query: "sinv-9" }).map((i) => i.docname)).toEqual(["SINV-9"]);
    expect(filterItems(items, { area: "All", query: "RETURN" }).map((i) => i.docname)).toEqual(["SINV-9"]);
    expect(filterItems(items, { area: "All", query: "fatima" }).map((i) => i.docname)).toEqual(["ACC-JV-1", "SINV-9"]);
  });

  it("ignores spaces around the query", () => {
    expect(filterItems(items, { area: "All", query: "  omar  " }).map((i) => i.docname)).toEqual(["PINV-7"]);
  });

  it("combines area and query", () => {
    expect(filterItems(items, { area: "Sales", query: "fatima" }).map((i) => i.docname)).toEqual(["SINV-9"]);
    expect(filterItems(items, { area: "Accounts", query: "omar" })).toEqual([]);
  });

  it("does not match on fields outside the four searched", () => {
    expect(filterItems(items, { area: "All", query: "Approval Pending" })).toEqual([]);
  });
});

describe("sortItems", () => {
  const NOW = Date.parse("2026-11-19T12:00:00");
  const a = item({ docname: "A", created: "2026-11-16T09:00:00", days: 3 });
  const b = item({ docname: "B", created: "2026-11-18T15:30:00", days: 1 });
  const c = item({ docname: "C", created: "2026-11-17T08:00:00", days: 2 });
  const names = (list: typeof items) => list.map((i) => i.docname);

  it("priority keeps the given order and returns the same list", () => {
    const given = [a, b, c];
    expect(sortItems(given, "priority", NOW)).toBe(given);
  });

  it("newest puts the latest arrival first", () => {
    expect(names(sortItems([a, b, c], "newest", NOW))).toEqual(["B", "C", "A"]);
  });

  it("oldest puts the earliest arrival first", () => {
    expect(names(sortItems([a, b, c], "oldest", NOW))).toEqual(["A", "C", "B"]);
  });

  it("orders two documents of the same day by the minute", () => {
    const early = item({ docname: "EARLY", created: "2026-11-18T09:00:00", days: 1 });
    const late = item({ docname: "LATE", created: "2026-11-18T17:45:00", days: 1 });
    expect(names(sortItems([early, late], "newest", NOW))).toEqual(["LATE", "EARLY"]);
    expect(names(sortItems([late, early], "oldest", NOW))).toEqual(["EARLY", "LATE"]);
  });

  it("keeps the given order for documents that arrived at the same moment", () => {
    const x = item({ docname: "X", created: "2026-11-18T10:00:00" });
    const y = item({ docname: "Y", created: "2026-11-18T10:00:00" });
    expect(names(sortItems([x, y], "newest", NOW))).toEqual(["X", "Y"]);
    expect(names(sortItems([x, y], "oldest", NOW))).toEqual(["X", "Y"]);
  });

  it("falls back to the age in days when the arrival time is missing or unreadable", () => {
    const old = item({ docname: "OLD", created: "", days: 40 });
    const fresh = item({ docname: "FRESH", created: "not a date", days: 0 });
    const mid = item({ docname: "MID", created: "2026-11-10T00:00:00", days: 9 });
    expect(names(sortItems([old, mid, fresh], "newest", NOW))).toEqual(["FRESH", "MID", "OLD"]);
  });

  it("does not change the list it is given", () => {
    const given = [a, b, c];
    sortItems(given, "newest", NOW);
    expect(names(given)).toEqual(["A", "B", "C"]);
  });
});
