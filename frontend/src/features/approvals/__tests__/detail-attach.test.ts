import { describe, expect, it } from "vitest";
import {
  MAX_ATTACHMENT_BYTES,
  attachmentName,
  checkAttachment,
  sizeLabel,
  withExtension,
} from "../detail-attach";

describe("checkAttachment", () => {
  it("accepts photos, PDFs and office files", () => {
    expect(checkAttachment({ size: 500, type: "image/jpeg" })).toBeNull();
    expect(checkAttachment({ size: 500, type: "application/pdf" })).toBeNull();
    expect(checkAttachment({ size: 500, type: "text/csv" })).toBeNull();
  });
  it("refuses an empty file", () => {
    expect(checkAttachment({ size: 0, type: "image/png" })).toBe("empty");
  });
  it("refuses a type the desk would not take as an attachment here", () => {
    expect(checkAttachment({ size: 10, type: "application/x-msdownload" })).toBe("type");
    expect(checkAttachment({ size: 10, type: "" })).toBe("type");
  });
  it("caps documents but lets a large photo through to be shrunk", () => {
    expect(checkAttachment({ size: MAX_ATTACHMENT_BYTES + 1, type: "application/pdf" })).toBe("tooLarge");
    expect(checkAttachment({ size: MAX_ATTACHMENT_BYTES + 1, type: "image/jpeg" })).toBeNull();
  });
});

describe("attachmentName", () => {
  it("keeps a good name", () => {
    expect(attachmentName({ name: "cheque.pdf", type: "application/pdf" })).toBe("cheque.pdf");
  });
  it("drops any folder part", () => {
    expect(attachmentName({ name: "C:\\Users\\x\\scan.jpg", type: "image/jpeg" })).toBe("scan.jpg");
    expect(attachmentName({ name: "a/b/scan.jpg", type: "image/jpeg" })).toBe("scan.jpg");
  });
  it("gives a nameless camera shot a name and extension", () => {
    expect(attachmentName({ name: "", type: "image/jpeg" }, 1700000000000)).toBe("attachment-1700000000000.jpg");
  });
  it("adds the extension the type implies when the name has none", () => {
    expect(attachmentName({ name: "scan", type: "image/png" })).toBe("scan.png");
    expect(attachmentName({ name: "scan", type: "application/weird" })).toBe("scan.bin");
  });
});

describe("withExtension", () => {
  it("swaps the extension", () => {
    expect(withExtension("scan.png", "jpg")).toBe("scan.jpg");
    expect(withExtension("photo.final.png", "jpg")).toBe("photo.final.jpg");
  });
  it("adds one when there was none", () => {
    expect(withExtension("scan", "jpg")).toBe("scan.jpg");
  });
});

describe("sizeLabel", () => {
  it("shows KB below a megabyte and MB above", () => {
    expect(sizeLabel(300)).toBe("1 KB");
    expect(sizeLabel(320 * 1024)).toBe("320 KB");
    expect(sizeLabel(1.5 * 1024 * 1024)).toBe("1.5 MB");
  });
});
