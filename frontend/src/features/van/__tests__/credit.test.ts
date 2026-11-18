import { describe, expect, it } from "vitest";
import type { CreditStatus } from "@/api/customer";
import { creditImpact, creditRefusal, usedShare } from "../credit";

function status(over: Partial<CreditStatus> = {}): CreditStatus {
  return {
    customer: "C1",
    credit_limit: 5000,
    used: 1200,
    available: 3800,
    overdue: null,
    credit_allowed: true,
    credit_problem: null,
    cash_exempt: false,
    blocking_overdue: null,
    approval: null,
    branch: null,
    ...over,
  };
}

describe("creditRefusal", () => {
  it("never refuses cash", () => {
    expect(creditRefusal(status({ credit_allowed: false, credit_problem: "no" }), "cash")).toBeNull();
  });
  it("refuses credit and cheque without an allowed limit", () => {
    const s = status({ credit_allowed: false, credit_problem: "C1 has no credit limit" });
    expect(creditRefusal(s, "credit")).toBe("C1 has no credit limit");
    expect(creditRefusal(s, "cheque")).toBe("C1 has no credit limit");
  });
  it("a blocking overdue stops credit but not a cheque", () => {
    const s = status({ blocking_overdue: { name: "SINV-1", posting_date: "2026-09-01", outstanding_amount: 800 } });
    expect(creditRefusal(s, "credit")).toContain("SINV-1");
    expect(creditRefusal(s, "cheque")).toBeNull();
  });
  it("nothing known, nothing refused", () => {
    expect(creditRefusal(null, "credit")).toBeNull();
  });
});

describe("creditImpact", () => {
  it("a credit sale within the limit", () => {
    const i = creditImpact(status(), "credit", 1000);
    expect(i).toMatchObject({ counts: true, over: false, after: 2200, availableAfter: 2800 });
  });
  it("a credit sale over the limit", () => {
    const i = creditImpact(status(), "credit", 4000);
    expect(i.over).toBe(true);
    expect(i.overBy).toBe(200);
  });
  it("cash is exempt only where the site says so", () => {
    expect(creditImpact(status({ cash_exempt: true }), "cash", 9000)).toMatchObject({ exempt: true, counts: false, over: false });
    expect(creditImpact(status(), "cash", 9000).over).toBe(true);
  });
  it("no limit: never over", () => {
    const i = creditImpact(status({ credit_limit: 0, available: null }), "credit", 1e6);
    expect(i).toMatchObject({ counts: true, over: false, availableAfter: null });
  });
  it("branch sub-limit", () => {
    const s = status({ branch: { name: "DMM", limit: 1500, used: 1000, available: 500 } });
    expect(creditImpact(s, "credit", 400).branchOver).toBe(false);
    expect(creditImpact(s, "credit", 600).branchOver).toBe(true);
  });
  it("an order with no payment type counts whole", () => {
    expect(creditImpact(status(), undefined, 1000)).toMatchObject({ counts: true, after: 2200 });
  });
});

describe("usedShare", () => {
  it("clamps to 0..1", () => {
    expect(usedShare(1200, 5000)).toBeCloseTo(0.24);
    expect(usedShare(9000, 5000)).toBe(1);
    expect(usedShare(100, 0)).toBe(0);
  });
});
