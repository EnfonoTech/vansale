import { describe, expect, it } from "vitest";
import { bulkShared, canConfirm } from "../rules";
import { flag, item, spec } from "./fixtures";

describe("canConfirm", () => {
  const none = { comment: "", hasAttachment: false, addedAttachment: false };

  it("a plain approve needs nothing", () => {
    expect(canConfirm(spec(), none)).toEqual({ ok: true, missing: [] });
  });

  it("a reject (return for correction) with an empty comment is missing the comment", () => {
    const reject = spec({ action: "Reject", tone: "reject", is_return_for_correction: true });
    expect(canConfirm(reject, none)).toEqual({ ok: false, missing: ["comment"] });
  });

  it("a whitespace-only comment counts as empty", () => {
    const reject = spec({ action: "Reject", tone: "reject", require_comment: true });
    expect(canConfirm(reject, { ...none, comment: "   \n " })).toEqual({ ok: false, missing: ["comment"] });
    expect(canConfirm(reject, { ...none, comment: "Wrong account" })).toEqual({ ok: true, missing: [] });
  });

  it("an attachment is missing when the document has none and none was added", () => {
    const needs = spec({ require_attachment: true });
    expect(canConfirm(needs, none)).toEqual({ ok: false, missing: ["attachment"] });
  });

  it("an attachment already on the document, or one just added, satisfies it", () => {
    const needs = spec({ require_attachment: true });
    expect(canConfirm(needs, { ...none, hasAttachment: true }).ok).toBe(true);
    expect(canConfirm(needs, { ...none, addedAttachment: true }).ok).toBe(true);
  });

  it("reports the comment before the attachment when both are missing", () => {
    const both = spec({ require_comment: true, require_attachment: true });
    expect(canConfirm(both, none)).toEqual({ ok: false, missing: ["comment", "attachment"] });
  });

  it("a recommendation is always ok, whatever the transition requires", () => {
    const advice = spec({
      recommend_only: true,
      require_comment: true,
      require_attachment: true,
      is_return_for_correction: true,
    });
    expect(canConfirm(advice, none)).toEqual({ ok: true, missing: [] });
  });
});

describe("bulkShared", () => {
  it("nothing selected shares nothing and has no complaint", () => {
    expect(bulkShared([])).toEqual({ actions: [], reason: null });
  });

  it("items of different document types cannot be decided together", () => {
    const r = bulkShared([item(), item({ doctype: "Payment Entry", docname: "ACC-PAY-1" })]);
    expect(r.actions).toEqual([]);
    expect(r.reason).toBeTruthy();
  });

  it("two journal entries sharing Approve and Reject offer both", () => {
    const r = bulkShared([
      item({ docname: "JV-1" }),
      item({ docname: "JV-2", available_actions: [flag("Reject"), flag("Approve")] }),
    ]);
    expect(r.reason).toBeNull();
    expect(r.actions.map((a) => a.action)).toEqual(["Approve", "Reject"]);
  });

  it("only actions present in every item are offered", () => {
    const r = bulkShared([
      item({ docname: "JV-1", available_actions: [flag("Approve"), flag("Reject")] }),
      item({ docname: "JV-2", available_actions: [flag("Approve")] }),
    ]);
    expect(r.actions.map((a) => a.action)).toEqual(["Approve"]);
  });

  it("an action that requires an attachment is dropped", () => {
    const r = bulkShared([
      item({ docname: "JV-1", available_actions: [flag("Approve", { require_attachment: true }), flag("Reject")] }),
      item({ docname: "JV-2", available_actions: [flag("Approve", { require_attachment: true }), flag("Reject")] }),
    ]);
    expect(r.actions.map((a) => a.action)).toEqual(["Reject"]);
  });

  it("an action is dropped when any one item needs an attachment for it", () => {
    const r = bulkShared([
      item({ docname: "JV-1", available_actions: [flag("Approve")] }),
      item({ docname: "JV-2", available_actions: [flag("Approve", { require_attachment: true })] }),
    ]);
    expect(r.actions).toEqual([]);
  });

  it("a comment required by any item is required of the shared action", () => {
    const r = bulkShared([
      item({ docname: "JV-1", available_actions: [flag("Reject")] }),
      item({ docname: "JV-2", available_actions: [flag("Reject", { require_comment: true })] }),
    ]);
    expect(r.actions).toEqual([flag("Reject", { require_comment: true })]);
  });

  it("a single item offers its own actions", () => {
    const r = bulkShared([item()]);
    expect(r.reason).toBeNull();
    expect(r.actions.map((a) => a.action)).toEqual(["Approve", "Reject"]);
  });
});
