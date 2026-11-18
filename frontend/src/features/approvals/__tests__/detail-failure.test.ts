import { describe, expect, it } from "vitest";
import { failureOf } from "../detail-failure";

function named(name: string, message: string, serverMessage?: string): Error {
  const error = new Error(message) as Error & { serverMessage?: string };
  error.name = name;
  error.serverMessage = serverMessage;
  return error;
}

describe("failureOf", () => {
  it("passes a server refusal on as the server worded it", () => {
    expect(failureOf(named("ApiError", "x", "Document has been modified"))).toEqual({
      kind: "server",
      message: "Document has been modified",
    });
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
