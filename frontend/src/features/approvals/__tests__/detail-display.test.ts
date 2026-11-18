import { describe, expect, it } from "vitest";
import type { Route } from "@/api/approvals";
import {
  bannerMessage,
  barMode,
  cameFromInbox,
  currentHolders,
  initials,
  moreLines,
  normalizePriority,
  orderActions,
  priorityPillTone,
} from "../detail-display";
import { spec } from "./fixtures";

describe("normalizePriority", () => {
  it("keeps a valid priority, any case", () => {
    expect(normalizePriority("High")).toBe("High");
    expect(normalizePriority(" critical ")).toBe("Critical");
    expect(normalizePriority("low")).toBe("Low");
  });
  it("falls back to Medium", () => {
    expect(normalizePriority("")).toBe("Medium");
    expect(normalizePriority("Urgent")).toBe("Medium");
    expect(normalizePriority(null)).toBe("Medium");
    expect(normalizePriority(undefined)).toBe("Medium");
  });
});

describe("priorityPillTone", () => {
  it("is red for Critical and High, amber for Medium, green for Low", () => {
    expect(priorityPillTone("Critical")).toBe("danger");
    expect(priorityPillTone("High")).toBe("danger");
    expect(priorityPillTone("Medium")).toBe("warning");
    expect(priorityPillTone("Low")).toBe("success");
    expect(priorityPillTone("")).toBe("warning");
  });
});

describe("barMode", () => {
  const approve = [spec()];

  it("offers the actions when nothing blocks them", () => {
    expect(barMode({ banner: null, actions: approve })).toEqual({ kind: "actions" });
  });
  it("keeps the recommendation buttons under a recommend banner", () => {
    const actions = [spec({ recommend_only: true })];
    expect(barMode({ banner: { kind: "recommend", forwarder: "Mariam K." }, actions })).toEqual({ kind: "actions" });
  });
  it("has nothing for a recommend banner without actions", () => {
    expect(barMode({ banner: { kind: "recommend", forwarder: "" }, actions: [] })).toEqual({ kind: "none" });
  });
  it("replaces the bar with the reason for waiting, self-owned and cannot-read", () => {
    for (const banner of [
      { kind: "waiting", holder: "Mariam K." },
      { kind: "self_owned" },
      { kind: "cannot_read" },
    ] as const) {
      expect(barMode({ banner, actions: [] })).toEqual({ kind: "reason", banner });
    }
  });
  it("never shows buttons beside a blocking banner, even if the server sent some", () => {
    expect(barMode({ banner: { kind: "self_owned" }, actions: approve }).kind).toBe("reason");
  });
  it("has nothing for a document the user has no action on", () => {
    expect(barMode({ banner: null, actions: [] })).toEqual({ kind: "none" });
  });
});

describe("bannerMessage", () => {
  it("names who asked for advice, or says it without a name", () => {
    expect(bannerMessage({ kind: "recommend", forwarder: "Mariam K." })).toEqual({
      key: "approvalsDetail.banner.recommend",
      params: { name: "Mariam K." },
    });
    expect(bannerMessage({ kind: "recommend", forwarder: "" }).key).toBe("approvalsDetail.banner.recommendAnon");
  });
  it("names who holds a waiting document, or says it without a name", () => {
    expect(bannerMessage({ kind: "waiting", holder: "Shafeek" }).params).toEqual({ name: "Shafeek" });
    expect(bannerMessage({ kind: "waiting", holder: "" }).key).toBe("approvalsDetail.banner.waitingAnon");
  });
  it("has one sentence each for self-owned and cannot-read", () => {
    expect(bannerMessage({ kind: "self_owned" }).key).toBe("approvalsDetail.banner.selfOwned");
    expect(bannerMessage({ kind: "cannot_read" }).key).toBe("approvalsDetail.banner.cannotRead");
  });
});

describe("orderActions", () => {
  it("puts other actions first, Reject next, Approve last", () => {
    const ordered = orderActions([
      spec({ action: "Approve", tone: "approve" }),
      spec({ action: "Send Back", tone: "other" }),
      spec({ action: "Reject", tone: "reject" }),
    ]);
    expect(ordered.map((a) => a.action)).toEqual(["Send Back", "Reject", "Approve"]);
  });
  it("keeps the server order within a tone and does not touch the input", () => {
    const input = [
      spec({ action: "B", tone: "other" }),
      spec({ action: "A", tone: "other" }),
    ];
    expect(orderActions(input).map((a) => a.action)).toEqual(["B", "A"]);
    expect(input.map((a) => a.action)).toEqual(["B", "A"]);
  });
});

describe("moreLines", () => {
  it("counts the lines the preview leaves out", () => {
    expect(moreLines({ rows: [["a"], ["b"]], total: 4 })).toBe(2);
  });
  it("is never negative", () => {
    expect(moreLines({ rows: [["a"], ["b"]], total: 1 })).toBe(0);
    expect(moreLines({ rows: [], total: 0 })).toBe(0);
  });
});

describe("currentHolders", () => {
  const route = (roles: Route["roles"]): Route => ({ chain: [], roles, events: [], current: "", finished: false });
  const mariam = { user: "mariam@x.com", full_name: "Mariam K." };
  const me = { user: "me@x.com", full_name: "Me" };

  it("lists the others who can act now, not the viewer", () => {
    const holders = currentHolders(route([{ role: "Accounts Manager", users: [me, mariam], count: 2 }]), "me@x.com");
    expect(holders).toEqual([{ role: "Accounts Manager", names: ["Mariam K."], more: 0, includesMe: true }]);
  });
  it("counts holders beyond the ones named", () => {
    const holders = currentHolders(route([{ role: "Finance Head", users: [mariam], count: 5 }]), "me@x.com");
    expect(holders[0]).toMatchObject({ names: ["Mariam K."], more: 4, includesMe: false });
  });
  it("leaves out a role nobody else holds", () => {
    expect(currentHolders(route([{ role: "Finance Head", users: [], count: 0 }]), "me@x.com")).toEqual([]);
  });
  it("keeps a role the viewer alone holds, so the screen can say 'you'", () => {
    const holders = currentHolders(route([{ role: "Finance Head", users: [me], count: 1 }]), "me@x.com");
    expect(holders).toEqual([{ role: "Finance Head", names: [], more: 0, includesMe: true }]);
  });
  it("falls back to the user id when a full name is missing", () => {
    const nameless = { user: "x@y.com", full_name: "" };
    expect(currentHolders(route([{ role: "R", users: [nameless], count: 1 }]), "me@x.com")[0].names).toEqual(["x@y.com"]);
  });
});

describe("initials", () => {
  it("takes the first and last word", () => {
    expect(initials("Mariam K.")).toBe("MK");
    expect(initials("Arathi Prakash Kumar")).toBe("AK");
  });
  it("copes with one word, empty and Arabic", () => {
    expect(initials("Shafeek")).toBe("S");
    expect(initials("  ")).toBe("?");
    expect(initials("مريم خالد")).toBe("مخ");
  });
});

describe("cameFromInbox", () => {
  it("is true for the inbox, with or without a query or trailing slash", () => {
    expect(cameFromInbox("/approvals")).toBe(true);
    expect(cameFromInbox("/approvals/")).toBe(true);
    expect(cameFromInbox("/approvals?tab=mine")).toBe(true);
    expect(cameFromInbox("/vansale/approvals")).toBe(true);
  });
  it("is false for a detail, another screen, or nothing", () => {
    expect(cameFromInbox("/approvals/Journal%20Entry/ACC-JV-1")).toBe(false);
    expect(cameFromInbox("/invoices")).toBe(false);
    expect(cameFromInbox(null)).toBe(false);
    expect(cameFromInbox(undefined)).toBe(false);
  });
});
