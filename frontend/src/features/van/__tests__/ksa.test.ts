import { describe, expect, it } from "vitest";
import { ksaAddressErrors, ksaVatError } from "@/features/van/ksa";

describe("KSA customer rules", () => {
  it("VAT: 15 digits starting and ending with 3", () => {
    expect(ksaVatError("300000000000003")).toBeNull();
    expect(ksaVatError("123456789012345")).not.toBeNull();
    expect(ksaVatError("30000000000003")).not.toBeNull();
    expect(ksaVatError("")).toBeNull();
    expect(ksaVatError("123", "United Arab Emirates")).toBeNull();
  });

  it("formats: building 4 digits, postal code 5 digits", () => {
    expect(ksaAddressErrors({ isB2B: false, buildingNumber: "123", pincode: "52388" })).toEqual([
      "Building number must be 4 digits",
    ]);
    expect(ksaAddressErrors({ isB2B: false, pincode: "5238" })).toEqual(["Postal code must be 5 digits"]);
  });

  it("B2B needs street, building, district, city, postal code", () => {
    expect(ksaAddressErrors({ isB2B: true, street: "King Rd", buildingNumber: "1234", city: "Buraydah" })).toEqual([
      "Required for B2B: District, Postal code",
    ]);
    expect(
      ksaAddressErrors({ isB2B: true, street: "K", buildingNumber: "1234", district: "D", city: "C", pincode: "52388" }),
    ).toEqual([]);
  });

  it("other countries are not checked", () => {
    expect(ksaAddressErrors({ isB2B: true, country: "India" })).toEqual([]);
  });
});
