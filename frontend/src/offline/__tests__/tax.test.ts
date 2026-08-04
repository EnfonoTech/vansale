/**
 * Tax arithmetic is the only code in the app that decides what a customer is
 * charged. It shipped for months as a hardcoded 15% with no test.
 */
import { describe, expect, it } from "vitest";
import { computeTaxTotals } from "@/features/van/tax";

const round = (n: number) => Math.round(n * 100) / 100;

describe("computeTaxTotals", () => {
  it("exclusive: adds tax on top of the typed rate", () => {
    const t = computeTaxTotals({ net: 100, ratePercent: 15, inclusive: false });
    expect(round(t.tax)).toBe(15);
    expect(round(t.grand)).toBe(115);
    expect(round(t.netOfTax)).toBe(100);
  });

  it("inclusive: backs tax OUT of the typed rate rather than adding it", () => {
    // 115 gross at 15% = 100 net + 15 tax. Adding on top would bill 132.25 —
    // overcharging by the full tax, which is the bug this pins.
    const t = computeTaxTotals({ net: 115, ratePercent: 15, inclusive: true });
    expect(round(t.tax)).toBe(15);
    expect(round(t.grand)).toBe(115);
    expect(round(t.netOfTax)).toBe(100);
  });

  it("inclusive and exclusive agree on the net for equivalent inputs", () => {
    const exc = computeTaxTotals({ net: 100, ratePercent: 15, inclusive: false });
    const inc = computeTaxTotals({ net: 115, ratePercent: 15, inclusive: true });
    expect(round(inc.netOfTax)).toBe(round(exc.netOfTax));
    expect(round(inc.grand)).toBe(round(exc.grand));
    expect(round(inc.tax)).toBe(round(exc.tax));
  });

  it("zero-rated customer gets no tax line", () => {
    const t = computeTaxTotals({ net: 250, ratePercent: 0, inclusive: false });
    expect(t.tax).toBe(0);
    expect(t.grand).toBe(250);
    expect(t.netOfTax).toBe(250);
  });

  it("zero rate is unaffected by the inclusive flag", () => {
    const t = computeTaxTotals({ net: 250, ratePercent: 0, inclusive: true });
    expect(t.tax).toBe(0);
    expect(t.grand).toBe(250);
  });

  it("discount is applied before tax in both modes", () => {
    const exc = computeTaxTotals({ net: 200, discount: 100, ratePercent: 15, inclusive: false });
    expect(round(exc.afterDiscount)).toBe(100);
    expect(round(exc.grand)).toBe(115);

    const inc = computeTaxTotals({ net: 230, discount: 115, ratePercent: 15, inclusive: true });
    expect(round(inc.afterDiscount)).toBe(115);
    expect(round(inc.grand)).toBe(115);
    expect(round(inc.netOfTax)).toBe(100);
  });

  it("handles a non-integer rate (5.5%) without drift", () => {
    const inc = computeTaxTotals({ net: 105.5, ratePercent: 5.5, inclusive: true });
    expect(round(inc.netOfTax)).toBe(100);
    expect(round(inc.tax)).toBe(5.5);
  });

  it("treats null/undefined discount as zero", () => {
    expect(computeTaxTotals({ net: 100, discount: null, ratePercent: 15, inclusive: false }).grand)
      .toBeCloseTo(115);
  });
});
