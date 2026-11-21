import { describe, expect, it } from "vitest";
import { buildTimeline, parseStamp } from "../detail-timeline";

describe("parseStamp", () => {
  it("reads Permission Manager's dd/MM/yy HH:mm", () => {
    expect(parseStamp("12/11/26 14:05")).toBe(new Date(2026, 10, 12, 14, 5).getTime());
  });
  it("reads a four-digit year and a bare date", () => {
    expect(parseStamp("03/01/2027")).toBe(new Date(2027, 0, 3).getTime());
  });
  it("reads an ISO date and time", () => {
    expect(parseStamp("2026-11-19 08:30:15")).toBe(new Date(2026, 10, 19, 8, 30, 15).getTime());
    expect(parseStamp("2026-11-19T08:30:15.123456")).toBe(new Date(2026, 10, 19, 8, 30, 15).getTime());
  });
  it("is null for text it cannot read, and for a date that does not exist", () => {
    expect(parseStamp("")).toBeNull();
    expect(parseStamp("yesterday")).toBeNull();
    expect(parseStamp("31/02/26 10:00")).toBeNull();
  });
});

describe("buildTimeline", () => {
  const comments = [
    { by: "Mariam K.", when: "12/11/26 09:00", text: "Looks fine" },
    { by: "Shafeek", when: "14/11/26 16:30", text: "Cheque number is missing" },
  ];
  const events = [
    { by: "Mohammed", user: "m@x.com", state: "Draft", to_state: "Pending", action: "Draft to Pending", on: "11/11/26 08:00" },
    { by: "", user: "mariam@x.com", state: "Pending", to_state: "Approved", action: "Pending to Approved", on: "13/11/26 10:15" },
  ];

  it("merges comments and state changes, newest first", () => {
    const timeline = buildTimeline(comments, events);
    expect(timeline.map((entry) => `${entry.kind}:${entry.when}`)).toEqual([
      "comment:14/11/26 16:30",
      "event:13/11/26 10:15",
      "comment:12/11/26 09:00",
      "event:11/11/26 08:00",
    ]);
  });
  it("shows the user id when an event has no full name", () => {
    const timeline = buildTimeline([], events);
    expect(timeline[0]).toMatchObject({ kind: "event", by: "mariam@x.com", from: "Pending", to: "Approved" });
  });
  it("puts what has no readable date last, in the order it came", () => {
    const undated = [
      { by: "A", when: "", text: "first" },
      { by: "B", when: "soon", text: "second" },
    ];
    const timeline = buildTimeline(undated, events);
    expect(timeline.slice(-2).map((entry) => (entry.kind === "comment" ? entry.text : ""))).toEqual(["first", "second"]);
    expect(timeline[0].kind).toBe("event");
  });
  it("is empty with nothing to show", () => {
    expect(buildTimeline([], [])).toEqual([]);
  });
});
