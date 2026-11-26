/**
 * The client calls: which method, path and parameters each one sends. The
 * server reads `names` of a bulk decision as a JSON string, and the flags
 * `return_to_originator` as 0 / 1, so those are pinned here.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiCall = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ apiCall }));

import * as api from "@/api/approvals";

const BASE = "vansale.steelforce.approvals";
const EXTRA = "vansale.steelforce.approvals_extra";

describe("approvals api", () => {
  beforeEach(() => {
    apiCall.mockReset();
    apiCall.mockResolvedValue({});
  });

  it("availability, inbox and count are plain GETs", async () => {
    await api.availability();
    await api.inbox();
    await api.count();
    expect(apiCall.mock.calls).toEqual([
      ["GET", `${BASE}.availability`],
      ["GET", `${BASE}.inbox`],
      ["GET", `${BASE}.count`],
    ]);
  });

  it("detail puts the document in the query string, encoded", async () => {
    await api.detail("Journal Entry", "ACC-JV/2026 #1");
    expect(apiCall).toHaveBeenCalledWith(
      "GET",
      `${BASE}.detail?doctype=Journal+Entry&name=ACC-JV%2F2026+%231`,
    );
  });

  it("apply posts the decision, comment, priority and the state the approver reviewed", async () => {
    await api.apply("Journal Entry", "JV-1", "Reject", "Wrong account", "High", "Pending Approval");
    expect(apiCall).toHaveBeenCalledWith("POST", `${BASE}.apply`, {
      doctype: "Journal Entry",
      name: "JV-1",
      action: "Reject",
      comment: "Wrong account",
      priority: "High",
      expected_state: "Pending Approval",
    });
  });

  it("apply sends no priority and no expected state unless it is given: blank means not chosen / not checked", async () => {
    await api.apply("Journal Entry", "JV-1", "Approve");
    expect(apiCall).toHaveBeenCalledWith("POST", `${BASE}.apply`, {
      doctype: "Journal Entry",
      name: "JV-1",
      action: "Approve",
      comment: "",
      priority: "",
      expected_state: "",
    });
  });

  it("applyBulk sends the names and the states they were listed in as JSON strings, as the server reads them", async () => {
    await api.applyBulk("Journal Entry", ["JV-1", "JV-2"], "Approve", "", "", {
      "JV-1": "Pending Approval",
      "JV-2": "Pending Approval",
    });
    expect(apiCall).toHaveBeenCalledWith(
      "POST",
      `${BASE}.apply_bulk`,
      {
        doctype: "Journal Entry",
        names: '["JV-1","JV-2"]',
        action: "Approve",
        comment: "",
        priority: "",
        expected_states: '{"JV-1":"Pending Approval","JV-2":"Pending Approval"}',
      },
      api.BULK_TIMEOUT_MS,
    );
  });

  it("applyBulk sends no priority and no states unless they are given", async () => {
    await api.applyBulk("Journal Entry", ["JV-1"], "Approve");
    expect(apiCall.mock.calls[0][2]).toMatchObject({ priority: "", expected_states: "" });
  });

  it("applyBulk waits two minutes, not the usual 20 seconds: the server decides the documents one by one", async () => {
    await api.applyBulk("Journal Entry", ["JV-1"], "Approve");
    expect(api.BULK_TIMEOUT_MS).toBe(120_000);
    expect(apiCall.mock.calls[0][3]).toBe(120_000);
  });

  it("no other call asks for a longer wait", async () => {
    await api.inbox();
    await api.apply("Journal Entry", "JV-1", "Approve");
    await api.history();
    for (const call of apiCall.mock.calls) expect(call).toHaveLength(call[0] === "POST" ? 3 : 2);
  });

  it("forwardTargets searches by the typed text", async () => {
    await api.forwardTargets("Journal Entry", "JV-1", "omar k");
    expect(apiCall).toHaveBeenCalledWith(
      "GET",
      `${EXTRA}.forward_targets?doctype=Journal+Entry&name=JV-1&query=omar+k`,
    );
  });

  it("forward sends the return switch as 0 or 1", async () => {
    await api.forward("PMWA-1", "omar@x", "please check", true);
    expect(apiCall).toHaveBeenLastCalledWith("POST", `${EXTRA}.forward`, {
      action_id: "PMWA-1",
      to_user: "omar@x",
      comment: "please check",
      return_to_originator: 1,
    });
    await api.forward("PMWA-1", "omar@x");
    expect(apiCall).toHaveBeenLastCalledWith("POST", `${EXTRA}.forward`, {
      action_id: "PMWA-1",
      to_user: "omar@x",
      comment: "",
      return_to_originator: 0,
    });
  });

  it("returnToOriginator posts the action and a comment", async () => {
    await api.returnToOriginator("PMWA-2", "done");
    expect(apiCall).toHaveBeenCalledWith("POST", `${EXTRA}.return_to_originator`, {
      action_id: "PMWA-2",
      comment: "done",
    });
  });

  it("attach posts the file as base64", async () => {
    await api.attach("Journal Entry", "JV-1", "scan.pdf", "QUJD");
    expect(apiCall).toHaveBeenCalledWith("POST", `${EXTRA}.attach`, {
      doctype: "Journal Entry",
      name: "JV-1",
      filename: "scan.pdf",
      content_base64: "QUJD",
    });
  });

  it("myRequests and sentBack are plain GETs", async () => {
    await api.myRequests();
    await api.sentBack();
    expect(apiCall.mock.calls).toEqual([
      ["GET", `${EXTRA}.my_requests`],
      ["GET", `${EXTRA}.sent_back`],
    ]);
  });

  it("history sends its limit and only the filters that are set", async () => {
    await api.history();
    expect(apiCall).toHaveBeenLastCalledWith("GET", `${EXTRA}.history?limit=100`);
    await api.history(50, "2026-11-01", "2026-11-19", "Sales Return");
    expect(apiCall).toHaveBeenLastCalledWith(
      "GET",
      `${EXTRA}.history?limit=50&from_date=2026-11-01&to_date=2026-11-19&transaction=Sales+Return`,
    );
  });
});
