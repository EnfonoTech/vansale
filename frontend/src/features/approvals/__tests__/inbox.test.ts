import { describe, expect, it } from "vitest";
import {
  ADVICE_ONLY_REASON,
  BULK_MAX,
  LIMIT_REASON,
  NO_SHARED_REASON,
  REVIEW_ONLY_REASON,
  actionTone,
  ageText,
  formatAmount,
  formatStamp,
  approvalsOnly,
  areaCounts,
  blockedReason,
  filterSections,
  isAdviceOnly,
  isOverdue,
  itemKey,
  parseServerTime,
  routeAllowedWithoutVan,
} from "../inbox";
import { BULK_MIXED_TYPES } from "../rules";
import { flag, item } from "./fixtures";

const jv1 = item({ docname: "JV-1", area: "Accounts", party: "Al Noor Trading", days: 3 });
const jv2 = item({ docname: "JV-2", area: "Accounts", party: "Gulf Steel Supply", days: 40 });
const pi1 = item({ docname: "PI-1", doctype: "Purchase Invoice", area: "Purchase", transaction: "Purchase Invoice" });
const so1 = item({ docname: "SO-1", doctype: "Sales Order", area: "Sales", transaction: "Sales Order" });

describe("itemKey", () => {
  it("tells apart two documents that share a name across types", () => {
    expect(itemKey(item({ doctype: "A", docname: "X" }))).not.toBe(itemKey(item({ doctype: "B", docname: "X" })));
  });
});

describe("isOverdue", () => {
  it("is more than 30 days, not 30", () => {
    expect(isOverdue(30)).toBe(false);
    expect(isOverdue(31)).toBe(true);
    expect(isOverdue(0)).toBe(false);
  });
});

describe("filterSections", () => {
  const sections = [
    { category: "Approval Pending", items: [jv1, pi1] },
    { category: "Decision Pending", items: [jv2] },
    { category: "Acknowledgement Pending", items: [so1] },
  ];

  it("keeps the server's order of sections and items", () => {
    const out = filterSections(sections, { area: "All", query: "" });
    expect(out.map((s) => s.category)).toEqual(["Approval Pending", "Decision Pending", "Acknowledgement Pending"]);
    expect(out[0].items.map((i) => i.docname)).toEqual(["JV-1", "PI-1"]);
  });

  it("drops a section that has nothing left", () => {
    const out = filterSections(sections, { area: "Accounts", query: "" });
    expect(out.map((s) => s.category)).toEqual(["Approval Pending", "Decision Pending"]);
    expect(out[0].items.map((i) => i.docname)).toEqual(["JV-1"]);
  });

  it("applies the search text inside the area", () => {
    const out = filterSections(sections, { area: "Accounts", query: "gulf" });
    expect(out).toEqual([{ category: "Decision Pending", items: [jv2] }]);
  });

  it("does not change what it was given", () => {
    filterSections(sections, { area: "Sales", query: "" });
    expect(sections[0].items).toHaveLength(2);
  });
});

describe("areaCounts", () => {
  it("counts every area and the total", () => {
    expect(areaCounts([jv1, jv2, pi1, so1])).toEqual({ All: 4, Accounts: 2, Purchase: 1, Sales: 1 });
  });

  it("is just the total for no items", () => {
    expect(areaCounts([])).toEqual({ All: 0 });
  });
});

describe("blockedReason", () => {
  it("lets anything join an empty selection that has a bulk action", () => {
    expect(blockedReason([], jv1)).toBeNull();
  });

  it("lets a second document of the same type and actions join", () => {
    expect(blockedReason([jv1], jv2)).toBeNull();
  });

  it("refuses another document type with the mixed-types key", () => {
    expect(blockedReason([jv1], pi1)).toBe(BULK_MIXED_TYPES);
  });

  it("refuses a document that shares no action with the selection", () => {
    const only = item({ docname: "JV-3", available_actions: [flag("Forward Only")] });
    expect(blockedReason([jv1], only)).toBe(NO_SHARED_REASON);
  });

  it("refuses a document whose only actions need an attachment (review it first)", () => {
    const needsFile = item({
      docname: "JV-4",
      available_actions: [flag("Approve", { require_attachment: true })],
    });
    expect(blockedReason([], needsFile)).toBe(REVIEW_ONLY_REASON);
    expect(blockedReason([jv1], needsFile)).toBe(REVIEW_ONLY_REASON);
  });

  it("stops at the batch cap, but keeps a selected document deselectable", () => {
    const many = Array.from({ length: BULK_MAX }, (_, n) => item({ docname: `FULL-${n}` }));
    expect(blockedReason(many, jv1)).toBe(LIMIT_REASON);
    expect(blockedReason(many, many[3])).toBeNull();
  });

  it("is not blocked when the candidate is already selected", () => {
    expect(blockedReason([jv1, jv2], jv1)).toBeNull();
  });

  describe("a document forwarded to the user with return-to-me (advice, not a decision)", () => {
    // The server turns every action on it into a recommendation: the document would not move.
    const advice = item({ docname: "JV-ADV", is_adhoc: true, return_to_originator: true, forwarded_by: "Mariam K." });

    it("cannot be ticked, alone or with others", () => {
      expect(blockedReason([], advice)).toBe(ADVICE_ONLY_REASON);
      expect(blockedReason([jv1], advice)).toBe(ADVICE_ONLY_REASON);
    });

    it("says so before the batch cap or a mismatch could", () => {
      const many = Array.from({ length: BULK_MAX }, (_, n) => item({ docname: `FULL-${n}` }));
      expect(blockedReason(many, advice)).toBe(ADVICE_ONLY_REASON);
      expect(blockedReason([pi1], advice)).toBe(ADVICE_ONLY_REASON);
    });

    it("is blocked even when it is somehow already in the selection", () => {
      expect(blockedReason([advice], advice)).toBe(ADVICE_ONLY_REASON);
    });

    it("is only when forwarded AND return-to-me: a plain forward acts like any document", () => {
      const plainForward = item({ docname: "JV-FWD", is_adhoc: true, return_to_originator: false, forwarded_by: "Mariam K." });
      expect(blockedReason([], plainForward)).toBeNull();
      expect(blockedReason([jv1], plainForward)).toBeNull();
    });

    it("is not about a document the user forwarded away (that one is waiting, not theirs to decide)", () => {
      const mine = item({ docname: "JV-OUT", is_adhoc: true, return_to_originator: true, is_waiting: true });
      expect(isAdviceOnly(mine)).toBe(false);
    });
  });
});

describe("isAdviceOnly", () => {
  it("needs a forward, return-to-me, and the document to be the user's to answer", () => {
    expect(isAdviceOnly(item({ is_adhoc: true, return_to_originator: true }))).toBe(true);
    expect(isAdviceOnly(item({ is_adhoc: true, return_to_originator: false }))).toBe(false);
    expect(isAdviceOnly(item({ is_adhoc: false, return_to_originator: true }))).toBe(false);
    expect(isAdviceOnly(item())).toBe(false);
  });
});

describe("actionTone (mirrors the server's tone_of)", () => {
  // The action names PM has on sft-uat.
  it.each([
    ["Approve", "approve"],
    ["Reject", "reject"],
    ["Send for Approval", "approve"],
    ["Submit", "approve"],
    ["Request Cancellation", "other"],
    ["Reject Cancellation", "reject"],
    ["Send for Acceptance", "approve"],
    ["Approve Cancellation", "approve"],
    ["Accept", "approve"],
  ])("%s is %s", (action, tone) => {
    expect(actionTone(flag(action))).toBe(tone);
  });

  it("reads the name from its start, not from a word inside it", () => {
    expect(actionTone(flag("Approve Return"))).toBe("approve");
    expect(actionTone(flag("Approve Cancellation"))).toBe("approve");
    expect(actionTone(flag("Send for Rejection Review"))).toBe("approve");
    expect(actionTone(flag("Requested Changes Done"))).toBe("other");
  });

  it("ignores case and spaces around the name", () => {
    expect(actionTone(flag("  REJECT  "))).toBe("reject");
    expect(actionTone(flag("request cancellation"))).toBe("other");
  });

  it("treats a return-for-correction flag as reject whatever it is called", () => {
    expect(actionTone(flag("Revise", { is_return_for_correction: true }))).toBe("reject");
    expect(actionTone(flag("Approve", { is_return_for_correction: true }))).toBe("reject");
    expect(actionTone(flag("Request Cancellation", { is_return_for_correction: true }))).toBe("reject");
  });

  it("calls anything else approve, as the server does (no guessing from words like cancel or send back)", () => {
    expect(actionTone(flag("Send Back"))).toBe("approve");
    expect(actionTone(flag("Cancel"))).toBe("approve");
    expect(actionTone(flag("Review"))).toBe("approve");
    expect(actionTone(flag(""))).toBe("approve");
  });
});

describe("parseServerTime", () => {
  it("reads the server's UTC stamp", () => {
    expect(parseServerTime("2026-11-19T08:00:00Z")?.toISOString()).toBe("2026-11-19T08:00:00.000Z");
  });

  it("returns null for nothing or rubbish", () => {
    expect(parseServerTime("")).toBeNull();
    expect(parseServerTime("not a date")).toBeNull();
    expect(parseServerTime(undefined)).toBeNull();
  });
});

describe("approvalsOnly", () => {
  const on = { approvalsEnabled: true };

  it("is for a signed-in user whose settings say no van app and who has approvals", () => {
    expect(approvalsOnly({ defaults: { is_van_user: false }, hasVanShell: false, ...on })).toBe(true);
  });

  it("is not for a user who has the van app", () => {
    expect(approvalsOnly({ defaults: { is_van_user: true }, hasVanShell: true, ...on })).toBe(false);
  });

  it("waits for the settings: unknown is not approvals-only", () => {
    expect(approvalsOnly({ defaults: null, hasVanShell: false, ...on })).toBe(false);
    expect(approvalsOnly({ defaults: null, hasVanShell: true, ...on })).toBe(false);
  });

  it("is never the answer on a site without approvals: nobody is trapped in a shell with nothing in it", () => {
    expect(approvalsOnly({ defaults: { is_van_user: false }, hasVanShell: false, approvalsEnabled: false })).toBe(false);
    expect(approvalsOnly({ defaults: { is_van_user: true }, hasVanShell: true, approvalsEnabled: false })).toBe(false);
  });
});

describe("routeAllowedWithoutVan", () => {
  it.each(["approvals", "approval-detail", "more", "pin", "login", "setup"])("allows %s", (name) => {
    expect(routeAllowedWithoutVan(name)).toBe(true);
  });

  it.each([
    "dashboard",
    "customers",
    "customer-detail",
    "invoices",
    "invoice-new",
    "payment-new",
    "leads",
    "quotations",
    "orders",
    "returns",
    "route-today",
    "van-stock",
    "sync-errors",
    "sync-edit-entry",
    "print-view",
  ])("sends %s (a van screen) to approvals", (name) => {
    expect(routeAllowedWithoutVan(name)).toBe(false);
  });

  it("does not allow an unnamed route", () => {
    expect(routeAllowedWithoutVan(undefined)).toBe(false);
    expect(routeAllowedWithoutVan(null)).toBe(false);
    expect(routeAllowedWithoutVan(Symbol("x"))).toBe(false);
  });
});

describe("ageText", () => {
  const t = (key: string, named?: Record<string, unknown>) => (named ? `${key}:${named.count}` : key);

  it("says today for no days, and for rubbish", () => {
    expect(ageText(0, t)).toBe("approvalsInbox.age.today");
    expect(ageText(-2, t)).toBe("approvalsInbox.age.today");
    expect(ageText(Number.NaN, t)).toBe("approvalsInbox.age.today");
  });

  it("says one day for one", () => {
    expect(ageText(1, t)).toBe("approvalsInbox.age.one");
  });

  it("passes the count for more", () => {
    expect(ageText(34, t)).toBe("approvalsInbox.age.many:34");
  });
});

describe("formatAmount", () => {
  it("keeps the company's decimals, three for BHD and two for SAR", () => {
    expect(formatAmount(749.82, 3, "en-US")).toBe("749.820");
    expect(formatAmount(1250.5, 2, "en-US")).toBe("1,250.50");
  });

  it("shows zero for a number it cannot read", () => {
    expect(formatAmount(Number.NaN, 3, "en-US")).toBe("0.000");
  });
});

describe("formatStamp", () => {
  it("writes the date and the time", () => {
    const text = formatStamp(new Date(2026, 10, 19, 11, 30), "en-US");
    expect(text).toContain("Nov");
    expect(text).toContain("2026");
    expect(text).toMatch(/11:30/);
  });
});
