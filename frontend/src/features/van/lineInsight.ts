/**
 * Selling help on each line of an invoice / quotation / order: the last
 * price this customer paid for the item, and a warning when the lines ask
 * for more than the salesman's warehouse holds (the desk's Last Selling Rate
 * and stock warning).
 *
 * Both are hints: online only, silent on failure, and the server still
 * decides on save.
 */
import { ref, watch, type Ref } from "vue";
import { lastSales, stockLevels, type ItemRow, type PastSale, type StockLevel } from "@/api/item";
import { isOnline } from "@/app/online";

export interface InsightLine {
  item_code: string;
  qty: number;
  conversion_factor?: number;
}

/**
 * When the lines of this item together need more than the stock, what is
 * available in this line's unit; else null. Several lines of one item share
 * the stock, so they are added up (in the stock unit).
 */
export function stockShortage(
  line: InsightLine,
  lines: InsightLine[],
  stock: StockLevel | undefined,
): number | null {
  if (!stock || !stock.is_stock_item) return null;
  const need = lines
    .filter((l) => l.item_code === line.item_code)
    .reduce((s, l) => s + (Number(l.qty) || 0) * (Number(l.conversion_factor) || 1), 0);
  if (need <= stock.qty + 1e-9) return null;
  const cf = Number(line.conversion_factor) || 1;
  return Math.max(stock.qty, 0) / cf;
}

export function useLineInsight(opts: {
  customer: Ref<string>;
  lines: Ref<InsightLine[]>;
  warehouse: Ref<string | undefined>;
}) {
  /** Item → last sale to the current customer (null = never sold to them). */
  const last = ref<Record<string, PastSale | null>>({});
  /** Item → stock in the salesman's warehouse. */
  const stock = ref<Record<string, StockLevel>>({});
  let lastFor = "";

  /** Stock already known from the catalog row the line was picked from. */
  function noteStock(item: ItemRow) {
    if (typeof item.stock_qty !== "number" || item.is_stock_item === undefined) return;
    stock.value[item.item_code] = { qty: item.stock_qty, is_stock_item: Number(item.is_stock_item) ? 1 : 0 };
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  async function refresh() {
    if (!isOnline()) return;
    const codes = [...new Set(opts.lines.value.map((l) => l.item_code).filter(Boolean))];
    const customer = opts.customer.value;
    if (customer !== lastFor) {
      last.value = {};
      lastFor = customer;
    }
    const wantLast = customer ? codes.filter((c) => !(c in last.value)) : [];
    const wantStock = codes.filter((c) => !(c in stock.value));
    if (wantLast.length) {
      try {
        const res = await lastSales(customer, wantLast);
        if (customer === lastFor) {
          for (const c of wantLast) last.value[c] = res[c] ?? null;
        }
      } catch {
        /* a hint only */
      }
    }
    if (wantStock.length) {
      try {
        const res = await stockLevels(wantStock, opts.warehouse.value);
        for (const c of wantStock) if (res[c]) stock.value[c] = res[c];
      } catch {
        /* a hint only */
      }
    }
  }

  watch(
    [opts.customer, () => opts.lines.value.map((l) => l.item_code).join("|")],
    () => {
      clearTimeout(timer);
      timer = setTimeout(() => void refresh(), 250);
    },
    { immediate: true },
  );

  return {
    lastSale: (code: string) => last.value[code] ?? null,
    shortage: (line: InsightLine) => stockShortage(line, opts.lines.value, stock.value[line.item_code]),
    stockOf: (code: string) => stock.value[code],
    noteStock,
  };
}
