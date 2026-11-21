import { describe, expect, it } from "vitest";
import { failureOf, sheetOutcome } from "../detail-failure";

function named(name: string, message: string, serverMessage?: string, status?: number): Error {
  const error = new Error(message) as Error & { serverMessage?: string; status?: number };
  error.name = name;
  error.serverMessage = serverMessage;
  error.status = status;
  return error;
}

describe("failureOf", () => {
  it("passes a server refusal on as the server worded it", () => {
    expect(failureOf(named("ApiError", "x", "Document has been modified"))).toEqual({
      kind: "server",
      message: "Document has been modified",
    });
  });
  it("hands on a server message as plain text: no tags, entities decoded", () => {
    expect(failureOf(named("ApiError", "x", "<div>Row 3 &amp; 4: <b>Debit</b> must equal Credit</div>"))).toEqual({
      kind: "server",
      message: "Row 3 & 4: Debit must equal Credit",
    });
  });
  it("a server message that is only markup says nothing readable", () => {
    expect(failureOf(named("ApiError", "HTTP 417", "<br>"))).toEqual({ kind: "unknown", message: "" });
  });
  it("an ordinary error's text is plain too", () => {
    expect(failureOf(new Error("<i>boom</i> &lt;now&gt;"))).toEqual({ kind: "unknown", message: "boom <now>" });
  });
  it("says nothing of its own for an HTTP error without a readable message", () => {
    expect(failureOf(named("ApiError", "HTTP 500"))).toEqual({ kind: "unknown", message: "" });
    expect(failureOf(named("ApiError", "HTTP 500", "  "))).toEqual({ kind: "unknown", message: "" });
  });
  it("recognises a call that did not get through", () => {
    expect(failureOf(named("NetworkError", "Network unreachable"))).toEqual({ kind: "network", message: "" });
  });
  it("reads an ordinary error or string", () => {
    expect(failureOf(new Error(" boom "))).toEqual({ kind: "unknown", message: "boom" });
    expect(failureOf("plain")).toEqual({ kind: "unknown", message: "plain" });
    expect(failureOf(null)).toEqual({ kind: "unknown", message: "" });
  });
});

describe("sheetOutcome", () => {
  const refusal = named("ApiError", "x", "Not allowed for this document", 417);
  const down = named("NetworkError", "Network unreachable");

  describe("while attaching the file", () => {
    it("a server refusal is about the file: the sheet stays open with the server's words", () => {
      expect(sheetOutcome("attach", refusal)).toEqual({ kind: "file", message: "Not allowed for this document" });
    });
    it("a connection that dropped is a plain retry (a file added twice does no harm)", () => {
      expect(sheetOutcome("attach", down)).toEqual({ kind: "retry" });
    });
    it("any other failure is a retry", () => {
      expect(sheetOutcome("attach", new Error("tooLarge"))).toEqual({ kind: "retry" });
      expect(sheetOutcome("attach", named("ApiError", "HTTP 500", undefined, 500))).toEqual({ kind: "retry" });
    });
  });

  describe("while applying the decision", () => {
    it("a server refusal closes the sheet and carries the server's words", () => {
      expect(sheetOutcome("apply", refusal)).toEqual({ kind: "refused", message: "Not allowed for this document" });
    });
    it("a dropped connection or a timeout means the result is unknown, never a plain retry", () => {
      expect(sheetOutcome("apply", down)).toEqual({ kind: "unconfirmed" });
      expect(sheetOutcome("apply", named("NetworkError", "Request timed out"))).toEqual({ kind: "unconfirmed" });
    });
    it("a gateway error with no readable message is unknown too: the server may have finished", () => {
      for (const status of [502, 503, 504]) {
        expect(sheetOutcome("apply", named("ApiError", `HTTP ${status}`, undefined, status))).toEqual({
          kind: "unconfirmed",
        });
      }
    });
    it("a gateway error that carries a server message is a refusal", () => {
      expect(sheetOutcome("apply", named("ApiError", "x", "Try later", 503))).toEqual({
        kind: "refused",
        message: "Try later",
      });
    });
    it("any other failure is a retry", () => {
      expect(sheetOutcome("apply", named("ApiError", "HTTP 500", undefined, 500))).toEqual({ kind: "retry" });
      expect(sheetOutcome("apply", new Error("boom"))).toEqual({ kind: "retry" });
    });
  });
});
