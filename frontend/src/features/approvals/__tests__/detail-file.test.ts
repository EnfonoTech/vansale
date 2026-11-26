import { describe, expect, it } from "vitest";
import { fileAccess, fileLabel, isPrivateFile, isSitePath, safeLinkUrl } from "../detail-file";

const file = (over: Partial<{ name: string; url: string | null; is_private: boolean }> = {}) => ({
  name: "a1b2c3d4e5",
  url: "/files/cheque.jpg",
  is_private: false,
  ...over,
});

describe("fileAccess", () => {
  it("is a plain link on the web, private or not (the session cookie covers it)", () => {
    expect(fileAccess(file(), false)).toBe("link");
    expect(fileAccess(file({ url: "/private/files/cheque.jpg", is_private: true }), false)).toBe("link");
  });
  it("keeps a plain link for a public file on the phone", () => {
    expect(fileAccess(file(), true)).toBe("link");
  });
  it("downloads a private file on the phone", () => {
    expect(fileAccess(file({ url: "/private/files/cheque.jpg", is_private: true }), true)).toBe("download");
  });
  it("treats a file in /private/ as private even if the flag is missing", () => {
    expect(fileAccess(file({ url: "/private/files/cheque.jpg", is_private: false }), true)).toBe("download");
  });
  it("explains a private file it must not send the token to", () => {
    expect(fileAccess(file({ url: "https://other.example/private/files/x.pdf", is_private: true }), true)).toBe("explain");
    expect(fileAccess(file({ url: "//other.example/x.pdf", is_private: true }), true)).toBe("explain");
  });
  it("explains a file with no URL, anywhere", () => {
    expect(fileAccess(file({ url: null }), false)).toBe("explain");
    expect(fileAccess(file({ url: "" }), true)).toBe("explain");
  });
});

describe("isSitePath", () => {
  it("accepts a path on this site", () => {
    expect(isSitePath("/files/a.pdf")).toBe(true);
    expect(isSitePath("/private/files/a b.pdf")).toBe(true);
  });
  it("refuses a full URL, a protocol-relative one, a backslash trick and nothing", () => {
    expect(isSitePath("https://x.example/files/a.pdf")).toBe(false);
    expect(isSitePath("//x.example/files/a.pdf")).toBe(false);
    expect(isSitePath("/\\x.example/a.pdf")).toBe(false);
    expect(isSitePath("")).toBe(false);
    expect(isSitePath(null)).toBe(false);
    expect(isSitePath(undefined)).toBe(false);
  });
});

describe("isPrivateFile", () => {
  it("reads the flag or the folder", () => {
    expect(isPrivateFile(file({ is_private: true }))).toBe(true);
    expect(isPrivateFile(file({ url: "/private/files/x.pdf" }))).toBe(true);
    expect(isPrivateFile(file())).toBe(false);
    expect(isPrivateFile(file({ url: null }))).toBe(false);
  });
});

describe("fileLabel", () => {
  it("is the file's own name, from the end of its URL", () => {
    expect(fileLabel(file({ url: "/private/files/cheque-102601326.jpg" }))).toBe("cheque-102601326.jpg");
  });
  it("decodes the URL's escapes and ignores a query", () => {
    expect(fileLabel(file({ url: "/files/Al%20Noor%20cheque.pdf?v=2" }))).toBe("Al Noor cheque.pdf");
  });
  it("keeps the text when the escape is broken", () => {
    expect(fileLabel(file({ url: "/files/100%.pdf" }))).toBe("100%.pdf");
  });
  it("falls back to the record's name when there is no URL", () => {
    expect(fileLabel(file({ url: null }))).toBe("a1b2c3d4e5");
    expect(fileLabel(file({ url: "/files/" }))).toBe("a1b2c3d4e5");
  });
});

describe("safeLinkUrl", () => {
  it("keeps a path on this site and an http(s) address", () => {
    expect(safeLinkUrl("/files/cheque.jpg")).toBe("/files/cheque.jpg");
    expect(safeLinkUrl("/private/files/a%20b.pdf?fid=1")).toBe("/private/files/a%20b.pdf?fid=1");
    expect(safeLinkUrl(" https://cdn.example.com/x.pdf ")).toBe("https://cdn.example.com/x.pdf");
    expect(safeLinkUrl("http://cdn.example.com/x.pdf")).toBe("http://cdn.example.com/x.pdf");
  });
  it("never lets a script, a data address, a protocol-relative or a backslash address become a link", () => {
    expect(safeLinkUrl("javascript:alert(1)")).toBe("");
    expect(safeLinkUrl(" JavaScript:alert(1)")).toBe("");
    expect(safeLinkUrl("data:text/html,<script>1</script>")).toBe("");
    expect(safeLinkUrl("//evil.example.com/x")).toBe("");
    expect(safeLinkUrl("/\\evil.example.com/x")).toBe("");
    expect(safeLinkUrl("files/x.pdf")).toBe("");
    expect(safeLinkUrl("")).toBe("");
    expect(safeLinkUrl(null)).toBe("");
    expect(safeLinkUrl(undefined)).toBe("");
  });
});
