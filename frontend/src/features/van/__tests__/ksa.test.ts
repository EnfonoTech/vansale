import { describe, expect, it } from "vitest";
import { countryOptions, defaultCountry, ksaAddressErrors, ksaVatError, mobileProblem } from "@/features/van/ksa";

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

describe("company country and mobile", () => {
  it("a new customer starts in the company's country", () => {
    expect(defaultCountry("Bahrain")).toBe("Bahrain");
    expect(defaultCountry(null)).toBe("Saudi Arabia");
    expect(countryOptions("Bahrain")[0]).toBe("Saudi Arabia");
    expect(countryOptions("Egypt")[0]).toBe("Egypt");
  });

  it("mobile: required and minimum digits", () => {
    expect(mobileProblem("", true, 10)).toBe("Mobile number is required");
    expect(mobileProblem("", false, 10)).toBeNull();
    expect(mobileProblem("0551234567", true, 10)).toBeNull();
    // a Bahrain mobile (8 digits): fine where the company is not Saudi
    expect(mobileProblem("36123456", true, 0)).toBeNull();
    expect(mobileProblem("36123456", true, 10)).toBe("Mobile number needs at least 10 digits");
  });
});
