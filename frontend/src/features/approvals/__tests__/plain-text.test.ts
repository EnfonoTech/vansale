import { describe, expect, it } from "vitest";
import { plainText } from "../plain-text";

describe("plainText", () => {
  it("leaves plain text alone", () => {
    expect(plainText("Row 3: Debit must equal Credit")).toBe("Row 3: Debit must equal Credit");
    expect(plainText("")).toBe("");
  });

  it("strips tags, keeping the words", () => {
    expect(plainText("<b>Amount</b> is <span class='x'>too high</span>")).toBe("Amount is too high");
    expect(plainText('<a href="/app/x">JV-1</a> is locked')).toBe("JV-1 is locked");
  });

  it("turns line breaks and paragraph ends into line breaks, not run-together words", () => {
    expect(plainText("First<br>Second")).toBe("First\nSecond");
    expect(plainText("<p>One</p><p>Two</p>")).toBe("One\nTwo");
    expect(plainText("<ul><li>a</li><li>b</li></ul>")).toBe("a\nb");
  });

  it("unescapes the entities Frappe writes", () => {
    expect(plainText("Tom &amp; Jerry &lt;3 &quot;x&quot; &#39;y&#39; &apos;z&apos;")).toBe("Tom & Jerry <3 \"x\" 'y' 'z'");
    expect(plainText("a&nbsp;b")).toBe("a b");
    expect(plainText("&#65;&#x42;")).toBe("AB");
  });

  it("strips tags first, so an escaped tag survives as the text it was", () => {
    expect(plainText("&lt;script&gt;alert(1)&lt;/script&gt;")).toBe("<script>alert(1)</script>");
  });

  it("does not eat a bare less-than or greater-than that is not a tag", () => {
    expect(plainText("Qty 5 < 10 and 12 > 3")).toBe("Qty 5 < 10 and 12 > 3");
  });

  it("an entity it does not know is left as it is", () => {
    expect(plainText("a &unknown; b")).toBe("a &unknown; b");
  });

  it("an out-of-range numeric entity is left as it is", () => {
    expect(plainText("&#99999999;")).toBe("&#99999999;");
  });

  it("collapses runs of spaces and blank lines and trims", () => {
    expect(plainText("  a   b \n\n\n c  ")).toBe("a b\n\nc");
  });

  it("copes with nothing", () => {
    expect(plainText(null)).toBe("");
    expect(plainText(undefined)).toBe("");
  });
});
