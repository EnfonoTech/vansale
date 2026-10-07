/**
 * KSA (ZATCA) customer rules, mirrored from the server
 * (`vansale.api.customer._validate_ksa`) so the driver gets the message
 * before the request. Only applied when the country is Saudi Arabia.
 */

const KSA = "Saudi Arabia";

export function isKsa(country?: string | null): boolean {
  return (country || KSA) === KSA;
}

/** VAT number: 15 digits, starting and ending with 3. */
export function ksaVatError(vat?: string | null, country?: string | null): string | null {
  if (!vat || !isKsa(country)) return null;
  return /^3\d{13}3$/.test(vat.trim()) ? null : "VAT number must be 15 digits, starting and ending with 3";
}

export function ksaAddressErrors(a: {
  country?: string | null;
  isB2B: boolean;
  street?: string;
  buildingNumber?: string;
  district?: string;
  city?: string;
  pincode?: string;
}): string[] {
  if (!isKsa(a.country)) return [];
  const errors: string[] = [];
  if (a.buildingNumber && !/^\d{4}$/.test(a.buildingNumber.trim())) errors.push("Building number must be 4 digits");
  if (a.pincode && !/^\d{5}$/.test(a.pincode.trim())) errors.push("Postal code must be 5 digits");
  if (a.isB2B) {
    const missing = (
      [
        ["Street", a.street],
        ["Building number", a.buildingNumber],
        ["District", a.district],
        ["City", a.city],
        ["Postal code", a.pincode],
      ] as const
    )
      .filter(([, v]) => !(v && v.trim()))
      .map(([label]) => label);
    if (missing.length) errors.push(`Required for B2B: ${missing.join(", ")}`);
  }
  return errors;
}
