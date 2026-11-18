import { describe, expect, it } from "vitest";
import { stockShortage } from "../lineInsight";

describe("stockShortage", () => {
  const stock = { qty: 24, is_stock_item: 1 };

  it("enough stock: no warning", () => {
    const l = { item_code: "A", qty: 2, conversion_factor: 12 };
    expect(stockShortage(l, [l], stock)).toBeNull();
  });

  it("short: what is left, in the line's unit", () => {
    const l = { item_code: "A", qty: 3, conversion_factor: 12 };
    expect(stockShortage(l, [l], stock)).toBe(2);
  });

  it("lines of the same item share the stock", () => {
    const a = { item_code: "A", qty: 1, conversion_factor: 12 };
    const b = { item_code: "A", qty: 13, conversion_factor: 1 };
    const other = { item_code: "B", qty: 100, conversion_factor: 1 };
    expect(stockShortage(a, [a, b, other], stock)).toBe(2);
    expect(stockShortage(b, [a, b, other], stock)).toBe(24);
  });

  it("no warning for a non-stock item or unknown stock", () => {
    const l = { item_code: "S", qty: 5 };
    expect(stockShortage(l, [l], { qty: 0, is_stock_item: 0 })).toBeNull();
    expect(stockShortage(l, [l], undefined)).toBeNull();
  });

  it("nothing in stock: 0 left", () => {
    const l = { item_code: "A", qty: 1 };
    expect(stockShortage(l, [l], { qty: -3, is_stock_item: 1 })).toBe(0);
  });
});
