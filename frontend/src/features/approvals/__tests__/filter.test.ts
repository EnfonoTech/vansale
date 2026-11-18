import { describe, expect, it } from "vitest";
import { filterItems } from "../filter";
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
