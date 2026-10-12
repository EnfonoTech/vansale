/**
 * Stock quantity for display: in the item's sales unit too when it sells in a
 * unit other than its stock unit — "2.17 Carton · 26 Nos" — else "26 Nos".
 */
const num = (n: number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(n);

export function stockLabel(
  qty: number | null | undefined,
  stockUom: string | null | undefined,
  salesUom?: string | null,
  salesCf?: number | null,
): string {
  const q = Number(qty) || 0;
  const base = `${num(q)}${stockUom ? ` ${stockUom}` : ""}`;
  if (!salesUom || !salesCf || salesCf === 1 || salesUom === stockUom) return base;
  return `${num(q / salesCf)} ${salesUom} · ${base}`;
}
