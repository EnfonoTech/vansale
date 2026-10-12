import { describe, expect, it } from "vitest";
import { stockLabel } from "../stock";

describe("stockLabel", () => {
  it("shows the sales unit first when it differs", () => {
    expect(stockLabel(26, "Nos", "Carton", 12)).toBe("2.17 Carton · 26 Nos");
  });
  it("whole sales units", () => {
    expect(stockLabel(24, "Nos", "Carton", 12)).toBe("2 Carton · 24 Nos");
  });
  it("stock unit only when the item sells in it", () => {
    expect(stockLabel(26, "Nos")).toBe("26 Nos");
    expect(stockLabel(26, "Nos", "Nos", 1)).toBe("26 Nos");
    expect(stockLabel(26, "Nos", "Carton", null)).toBe("26 Nos");
  });
});
