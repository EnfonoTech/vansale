import { describe, expect, it } from "vitest";
import { ageLabel, priorityTone } from "../format";

describe("ageLabel", () => {
  it("says Today for 0", () => expect(ageLabel(0)).toBe("Today"));
  it("says 1 day for 1", () => expect(ageLabel(1)).toBe("1 day"));
  it("says N days otherwise", () => {
    expect(ageLabel(7)).toBe("7 days");
    expect(ageLabel(45)).toBe("45 days");
  });
  it("never shows a negative or missing age", () => {
    expect(ageLabel(-2)).toBe("Today");
    expect(ageLabel(Number.NaN)).toBe("Today");
  });
});

describe("priorityTone", () => {
  it("maps each priority to its tone", () => {
    expect(priorityTone("Critical")).toBe("critical");
    expect(priorityTone("High")).toBe("high");
    expect(priorityTone("Medium")).toBe("medium");
    expect(priorityTone("Low")).toBe("low");
  });
  it("ignores case and spaces", () => {
    expect(priorityTone(" high ")).toBe("high");
    expect(priorityTone("CRITICAL")).toBe("critical");
  });
  it("treats anything unknown as medium", () => {
    expect(priorityTone("")).toBe("medium");
    expect(priorityTone("Urgent")).toBe("medium");
  });
});
