<script setup lang="ts">
/**
 * Sales invoice form — rewritten for Phase B.
 *
 * Features (per PDF 2026-04-20 §1):
 *  - Customer select + inline "new customer" hook (Phase C will wire)
 *  - Catalog: each click adds a new line (same item → multiple rows)
 *  - Per-line: qty, rate (editable), UOM select from item's UOMs,
 *              discount %, line total
 *  - Price List rate auto-fetched per (customer, item, uom)
 *  - Payment type toggle: Cash / Credit
 *  - Mode of payment select when Cash — invoice.save auto-adds payments row
 *  - Save as Draft / Save & Submit buttons
 *  - Tax preview (15% VAT) — real breakup appears on detail view after save
 *  - Sales person chip (auto-tagged by backend)
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listMine as listCustomers, customerLabel, type CustomerRow } from "@/api/customer";
import {
  listMine as listItems,
  detail as itemDetail,
  priceFor,
  type ItemRow,
  type ItemUom,
} from "@/api/item";
import { save, detail, updateDraft, taxInfo, type InvoiceItem, type TaxInfo } from "@/api/invoice";
import { modesOfPayment, type ModeOfPayment } from "@/api/payment";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { computeTaxTotals, netRateFactor } from "@/features/van/tax";
import Icon from "@/components/Icon.vue";
import { stockLabel } from "@/features/van/stock";
import SarSymbol from "@/components/SarSymbol.vue";
import SearchSelect from "@/components/SearchSelect.vue";
import { vDecimals } from "@/components/decimals";
import { revealOnFocus } from "@/components/reveal";
import { inputValue } from "@/components/liveInput";
import { confirmSubmit, withCurrency } from "@/stores/confirm";
import { precheckBeforeSubmit } from "@/api/precheck";
import { isOnline } from "@/app/online";
import { drivers as listDrivers, type DriverRow } from "@/api/steelforce";
import CreditPanel from "@/components/CreditPanel.vue";
import LineInsight from "@/components/LineInsight.vue";
import { useLineInsight } from "@/features/van/lineInsight";
import { creditRefusal, useCreditStatus, type PayType, saleBlock } from "@/features/van/credit";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();

const props = defineProps<{ name?: string }>();

// Edit mode: we're editing an existing draft invoice. Saved doc name is
// captured so submit can delete-old + save-new (drafts only — safe because
// no stock is posted and no GL entries exist until submit).
const editName = computed(() => props.name || String(route.params.name ?? ""));
const isEditMode = computed(() => Boolean(editName.value));

interface Line extends InvoiceItem {
  uoms?: ItemUom[];        // per-line UOM choices
  amount: number;          // computed
  min_rate?: number;       // lowest rate the site accepts for this line's UOM
}

/** The line's rate after its line discount — what the minimum is compared with. */
function effectiveRate(l: Line): number {
  const disc = session.lineDiscount ? Number(l.discount_percentage) || 0 : 0;
  return (Number(l.rate) || 0) * (1 - disc / 100);
}
/** A saved line's rate before its discount %, for the form's own discount math. */
function rateBeforeDiscount(rate: number, pct: number | undefined, listRate: number | undefined): number {
  const d = session.lineDiscount ? Number(pct) || 0 : 0;
  if (d <= 0) return Number(rate) || 0;
  if (d >= 100) return Number(listRate) || 0;
  return roundRate((Number(rate) || 0) / (1 - d / 100));
}
const belowMin = (l: Line) => Boolean(l.min_rate) && effectiveRate(l) + 0.0001 < (l.min_rate ?? 0);

const customers = ref<CustomerRow[]>([]);
const items = ref<ItemRow[]>([]);

const customer = ref(String(route.query.customer ?? ""));
const warehouse = computed(() => session.defaultWarehouse ?? "");
const lines = ref<Line[]>([]);
const itemSearch = ref("");
const remarks = ref("");
// Last price to this customer and short stock, under each line.
const insight = useLineInsight({ customer, lines, warehouse: computed(() => warehouse.value || undefined) });

// New invoices start on the "Default payment on invoice" setting; a reopened draft keeps its own.
const paymentType = ref<"cash" | "credit" | "cheque">(session.defaultPaymentType);
const modeOfPayment = ref<string>("Cash");
// Modes with an account for this company (server-filtered), not a fixed list.
const mops = ref<ModeOfPayment[]>([]);
// Post-dated cheque sale (Steel Force): the branch's cheque modes, number and date.
const chequeMops = ref<ModeOfPayment[]>([]);
const chequeMode = ref("");
const chequeNo = ref("");
// Today on the phone's calendar (toISOString alone is UTC: yesterday before 3am in KSA).
const chequeDate = ref(new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10));
// The cheque's amount (blank = all of it, or what the other modes leave) and,
// as in a split cash sale, other modes paying the rest now — the desk's cheque
// dialog takes cheque and other modes together.
const chequeAmount = ref<number | null>(null);
const chequeExtra = ref<PayRow[]>([]);
// Steel Force "Loyalty": a small amount written off when the customer pays
// (up to the company's maximum), on a sale paid now.
const loyalty = ref<number | null>(null);
const loyaltyOpen = ref(false);
// Advance already paid on the order this invoice bills (ERPNext applies it to
// the invoice): the customer is not asked for it again.
const orderAdvance = ref(0);
// Delivery person on a cash sale ("Ask for the delivery person" setting).
const driverList = ref<DriverRow[]>([]);
const driver = ref("");

/**
 * Split cash payment ("Split payment" setting): several modes on one sale,
 * e.g. Cash 60 + Card 40. A row left blank takes what's left; anything not
 * covered stays on credit.
 */
interface PayRow { mode: string; amount: number | null; reference: string }
const payRows = ref<PayRow[]>([]);
// A cash sale is paid on the spot. Only one handed to a delivery person asks
// "now or on delivery" (on delivery by default, as sf_trading's desk form).
const driverCollects = ref(true);
const pickedDriver = computed(() => driverList.value.find((d) => d.name === driver.value));
const driverName = computed(() => pickedDriver.value?.full_name || driver.value);
const collectLater = computed(() => paymentType.value === "cash" && Boolean(driver.value) && driverCollects.value);
function onDriverPicked() {
  driverCollects.value = true;
}
// Watched, not read once on mount: the settings can arrive after the form
// opens (first start, or right after login).
watch(
  () => session.askDriver,
  (on) => {
    if (on && !driverList.value.length) void listDrivers().then((d) => (driverList.value = d)).catch(() => {});
  },
  { immediate: true },
);
const useSplit = computed(() => session.splitPayment && paymentType.value === "cash" && !collectLater.value);

// The customer's credit (limit / used / overdue), shown in Payment. Credit or
// Cheque the customer can't have is refused on tap, with the reason.
const { status: credit, loading: creditLoading } = useCreditStatus(customer);
// An invoice made from an order: the order was already checked against the limit.
const fromOrder = ref(false);
const refusalFor = (t: PayType) => creditRefusal(credit.value, t);
function pickPayment(t: PayType) {
  const why = refusalFor(t) || (t !== "cash" ? saleBlock(null, t, { online: isOnline(), steelforce: session.steelforce }) : null);
  if (why && paymentType.value !== t) {
    toasts.warn(why);
    return;
  }
  paymentType.value = t;
}
// Cheque dated after today: post-dated, held until it can be banked.
const chequeDaysAhead = computed(() => {
  if (!chequeDate.value) return 0;
  const today = new Date(new Date().toISOString().slice(0, 10));
  return Math.round((new Date(chequeDate.value).getTime() - today.getTime()) / 86_400_000);
});
const needsReference = (mode: string) => Boolean(mops.value.find((m) => m.name === mode)?.needs_reference);

function addPayRow() {
  const used = new Set(payRows.value.map((r) => r.mode));
  const next = mops.value.find((m) => !used.has(m.name))?.name ?? modeOfPayment.value;
  payRows.value.push({ mode: next, amount: null, reference: "" });
}
function removePayRow(i: number) {
  payRows.value.splice(i, 1);
}
// As in the desk payment popup: tapping an empty amount fills what's left
// (total − the other rows).
function fillRest(i: number) {
  const row = payRows.value[i];
  if (row.amount != null && (row.amount as unknown) !== "" && Number(row.amount) !== 0) return;
  const others = payRows.value.reduce((s, r, j) => s + (j !== i ? Number(r.amount) || 0 : 0), 0);
  row.amount = round(Math.max(toPay.value - others, 0));
}

const discountAmount = ref<number | null>(null);

const busy = ref(false);
const savingDraft = ref(false);

// UOM cache — "customer|item_code" → uoms list, so re-adding the same item
// doesn't refetch. Keyed by customer too: prices differ per customer.
const uomCache = reactive<Record<string, ItemUom[]>>({});
const uomKey = (itemCode: string) => `${customer.value}|${itemCode}`;

/**
 * Tax comes from the server, never a constant.
 *
 * The form used to hardcode 15%, which was wrong for any non-KSA company and
 * for every zero-rated / exempt customer — and it silently assumed
 * tax-exclusive pricing. `tax_info` resolves the template through the
 * customer's Tax Category / Tax Rule and reports whether the rate is
 * `included_in_print_rate`.
 *
 * Starts at 0 rather than 15: showing no tax until the server answers is
 * honest, showing a made-up 15% is not.
 */
const tax = ref<TaxInfo>({ template: null, rate: 0, inclusive: false, simple: true, taxes: [] });

// Last tax info per customer, so an offline sale previews the real tax
// instead of 0% (the server always recomputes on save).
const TAX_CACHE_KEY = "vansale.taxInfo";

function cachedTaxInfo(): Record<string, TaxInfo> {
  try {
    return JSON.parse(localStorage.getItem(TAX_CACHE_KEY) || "{}") as Record<string, TaxInfo>;
  } catch {
    return {};
  }
}

async function loadTaxInfo() {
  const key = customer.value || "";
  try {
    tax.value = await taxInfo(customer.value || undefined);
    try {
      localStorage.setItem(TAX_CACHE_KEY, JSON.stringify({ ...cachedTaxInfo(), [key]: tax.value }));
    } catch {
      /* storage full / blocked */
    }
  } catch {
    // Offline: this customer's last tax info, else the default (no customer).
    const cached = cachedTaxInfo();
    const known = cached[key] ?? cached[""];
    if (known) tax.value = known;
  }
}

// The catalog only lists items with stock in this van (see `loadAll`), so
// distinguish "your search matched nothing" from "this van is empty" —
// the second one needs the office to post a transfer, not a retype.
// An order taker (invoice moves no stock) sees the whole price list.
const emptyCatalogHint = computed(() => {
  if (!session.updateStock) return itemSearch.value.trim() ? "No item matches that search." : "No items to sell.";
  if (itemSearch.value.trim()) return "No item in this van's stock matches that search.";
  return warehouse.value
    ? `No stock in ${warehouse.value}. Ask the office to transfer stock into the van.`
    : "No van warehouse assigned to your user. Ask the office to set one.";
});

/**
 * Customer picker options. The preloaded page is the offline set; typing hits
 * the server so a driver is never limited to whatever happened to be cached,
 * and results are merged rather than replaced so the current selection cannot
 * vanish from the list mid-edit.
 */
const customerOptions = computed(() =>
  // Title (e.g. English name) with the other name / VAT underneath — not the
  // customer ID, which on sites naming customers by name just repeats it.
  customers.value.map((c) => ({
    value: c.name,
    label: customerLabel(c),
    sub: [c.secondary_name, c.vat_number ? `VAT ${c.vat_number}` : ""]
      .filter(Boolean)
      .join(" · ") || (c.name !== customerLabel(c) ? c.name : ""),
    // Searched but not shown: code, both names, mobile, VAT.
    keywords: [c.name, c.customer_name, c.customer_name_2, c.mobile_no, c.vat_number].filter(Boolean).join(" "),
  })),
);

async function onCustomerSearch(termText: string) {
  try {
    const found = await listCustomers(termText || undefined, 50);
    const seen = new Set(customers.value.map((c) => c.name));
    for (const c of found) if (!seen.has(c.name)) customers.value.push(c);
  } catch {
    /* offline — local filtering over the cached page still works */
  }
}

const netTotal = computed(() => lines.value.reduce((s, l) => s + l.amount, 0));

// Arithmetic lives in `features/van/tax.ts` so it can be unit-tested — this is
// the only code that decides what a customer is charged.
const totals = computed(() =>
  computeTaxTotals({
    net: netTotal.value,
    discount: discountAmount.value,
    ratePercent: tax.value.rate,
    inclusive: tax.value.inclusive,
    // ERPNext additional discount, as the server posts it (setting).
    applyOn: session.applyDiscountOn,
  }),
);
const taxTotal = computed(() => totals.value.tax);
const grandTotal = computed(() => totals.value.grand);

// Loyalty is offered where it rides on the Payment Entry sf_trading makes: a
// cheque, or a cash sale paid now when the site posts cash that way.
const loyaltyAllowed = computed(() => {
  const l = session.loyalty;
  if (!l) return false;
  if (paymentType.value === "cheque") return true;
  return paymentType.value === "cash" && !collectLater.value && l.on_cash;
});
const loyaltyAmount = computed(() => (loyaltyAllowed.value ? Math.max(Number(loyalty.value) || 0, 0) : 0));
// What the customer pays: the total less the order's advance and the loyalty.
const toPay = computed(() => round(Math.max(grandTotal.value - orderAdvance.value, 0) - loyaltyAmount.value));
// The rest of a part-cheque sale is paid now in a cash / bank mode, not another cheque.
const restMops = computed(() => mops.value.filter((m) => !m.pdc));
// Cheque sale amounts: the cheque first, then the other modes. The first blank
// amount takes what is left (the cheque, while it is blank); other blanks are 0.
const isBlank = (v: unknown) => v == null || v === "";
const chequeRestAt = computed(() => [chequeAmount.value, ...chequeExtra.value.map((r) => r.amount)].findIndex(isBlank));
const chequeLines = computed(() => {
  const raw = [chequeAmount.value, ...chequeExtra.value.map((r) => r.amount)];
  const given = raw.reduce<number>((t, v) => t + (isBlank(v) ? 0 : Number(v) || 0), 0);
  return raw.map((v, i) =>
    isBlank(v) ? (i === chequeRestAt.value ? round(Math.max(toPay.value - given, 0)) : 0) : Number(v) || 0,
  );
});
const chequePart = computed(() => chequeLines.value[0] ?? 0);
const chequePaid = computed(() => round(chequeLines.value.reduce((t, n) => t + n, 0)));
// > 0: still to pay; < 0: more than the amount to pay.
const chequeShort = computed(() => round(toPay.value - chequePaid.value));
// A blank amount shows what it will take (the rest), greyed; tapping it fills
// that in, as "Tap for rest" on a split cash sale.
const chequeHint = (i: number) => (i === chequeRestAt.value ? money(chequeLines.value[i] ?? 0) : "Tap for rest");
function fillChequeRest(i: number) {
  const raw = [chequeAmount.value, ...chequeExtra.value.map((r) => r.amount)];
  if (!isBlank(raw[i]) && Number(raw[i]) !== 0) return;
  const others = raw.reduce<number>((t, v, j) => t + (j !== i && !isBlank(v) ? Number(v) || 0 : 0), 0);
  const rest = round(Math.max(toPay.value - others, 0));
  if (rest <= 0) return;
  if (i === 0) chequeAmount.value = rest;
  else chequeExtra.value[i - 1].amount = rest;
}
// One other mode always (the desk allows cheque + cash); more with "Split payment".
const canAddChequeRow = computed(() => restMops.value.length > 0 && (!chequeExtra.value.length || session.splitPayment));
function addChequeRow() {
  const used = new Set(chequeExtra.value.map((r) => r.mode));
  const free = restMops.value.filter((m) => !used.has(m.name));
  // Cash first, as on a cash sale; then the next mode not used yet.
  const next = free.find((m) => m.type === "Cash") ?? free[0] ?? restMops.value[0];
  if (next) chequeExtra.value.push({ mode: next.name, amount: null, reference: "" });
}
// The other modes of a cheque sale, with their worked-out amounts (none at 0).
function chequeRestRows() {
  return chequeExtra.value
    .map((r, i) => ({ mode_of_payment: r.mode, amount: chequeLines.value[i + 1] ?? 0, reference_no: r.reference || null }))
    .filter((r) => r.amount > 0.005);
}

// Split payment summary: entered amounts, plus one blank row taking the rest.
const splitPaid = computed(() => {
  const given = payRows.value.reduce((s, r) => s + (r.amount != null ? Number(r.amount) || 0 : 0), 0);
  const blank = payRows.value.some((r) => r.amount == null || (r.amount as unknown) === "");
  return round(blank ? Math.max(toPay.value, given) : given);
});
const splitCredit = computed(() => round(toPay.value - splitPaid.value));

// Single mode (split off): amount next to the mode, the full total by default
// (follows the total until the driver edits it); less = rest on credit.
const singleAmount = ref<number | null>(null);
const singleAmountModel = computed<number | string>({
  get: () => (singleAmount.value == null ? toPay.value : singleAmount.value),
  set: (v) => {
    const n = Number(v);
    singleAmount.value = (v as unknown) === "" || !Number.isFinite(n) ? null : n;
  },
});
const singleCredit = computed(() =>
  singleAmount.value == null ? 0 : round(Math.max(toPay.value - singleAmount.value, 0)),
);
const netOfTax = computed(() => totals.value.netOfTax);

/**
 * What ERPNext's credit-limit check counts for this sale. It runs at submit,
 * before a Payment Entry is made, so a cash sale posted by Payment Entry counts
 * whole; a POS cash sale counts only what is left unpaid.
 */
const unpaidPart = computed(() => {
  if (fromOrder.value) return 0;
  if (paymentType.value !== "cash" || collectLater.value) return grandTotal.value;
  if (session.$state.defaults?.cash_sale_posting === "Payment Entry") return grandTotal.value;
  return useSplit.value ? Math.max(splitCredit.value, 0) : singleCredit.value;
});

const selectedCustomer = computed(() =>
  customers.value.find((c) => c.name === customer.value),
);

// Re-price all lines when customer changes (different price list) — not
// when a draft being edited sets its own customer: its rates are the ones
// it was saved with.
let keepDraftRates = false;
watch(customer, async (newCustomer) => {
  if (!newCustomer) return;
  // Tax Category is per-customer, so the rate can change with the customer.
  void loadTaxInfo();
  if (keepDraftRates) {
    keepDraftRates = false;
    return;
  }
  for (const l of lines.value) {
    try {
      const p = await priceFor(l.item_code, newCustomer, l.uom, l.price_list);
      l.min_rate = p.min_rate ?? undefined;
      if (p.price_list_rate) {
        l.price_list_rate = roundRate(p.price_list_rate);
        l.rate = roundRate(p.price_list_rate);
        recalc(l);
      }
    } catch {
      /* ignore per-line failures */
    }
  }
});

async function loadModesOfPayment() {
  try {
    const all = await modesOfPayment();
    mops.value = all.filter((m) => !m.pdc);
    chequeMops.value = all.filter((m) => m.pdc);
    if (chequeMops.value.length && !chequeMops.value.some((m) => m.name === chequeMode.value)) {
      chequeMode.value = chequeMops.value[0].name;
    }
  } catch {
    mops.value = [];
  }
  // Keep the current choice valid: default to a Cash-type mode, else the first.
  if (mops.value.length && !mops.value.some((m) => m.name === modeOfPayment.value)) {
    modeOfPayment.value = (mops.value.find((m) => m.type === "Cash") ?? mops.value[0]).name;
  }
  if (!payRows.value.length) payRows.value = [{ mode: modeOfPayment.value, amount: null, reference: "" }];
}

async function loadAll() {
  void loadTaxInfo();
  void loadModesOfPayment();
  customers.value = await listCustomers(undefined, 200);
  // Opened for a customer outside the first page (e.g. from the customer
  // screen): fetch it, or the picker shows empty although one is chosen.
  if (customer.value && !customers.value.some((c) => c.name === customer.value)) {
    await onCustomerSearch(customer.value);
  }
  // `onlyInStock` — a van can only sell what it carries, and an item with
  // no incoming stock has no valuation rate, which ERPNext rejects at
  // submit time (surfacing as an unfixable sync error days later).
  items.value = await listItems(undefined, warehouse.value || undefined, 300, session.updateStock);
  if (isEditMode.value) {
    await prefillFromDraft(editName.value);
  } else if (route.query.restore === "1") {
    restoreCart();
  }
}

async function prefillFromDraft(name: string) {
  try {
    const doc = await detail(name);
    if (doc.docstatus !== 0) {
      toasts.error("Only draft invoices can be edited");
      void router.replace({ name: "invoice-detail", params: { name } });
      return;
    }
    keepDraftRates = customer.value !== doc.customer;
    customer.value = doc.customer;
    fromOrder.value = Boolean(doc.sales_order);
    remarks.value = doc.remarks || "";
    discountAmount.value = doc.discount_amount || null;
    // Keep the draft's own payment choice: the form defaults to Cash, and
    // saving with that default turned an unpaid credit draft into a paid one.
    paymentType.value = doc.payment_type ?? (doc.is_pos ? "cash" : "credit");
    if (doc.mode_of_payment) modeOfPayment.value = doc.mode_of_payment;
    if (paymentType.value === "cheque") {
      chequeMode.value = doc.mode_of_payment || chequeMode.value;
      chequeNo.value = doc.payments?.[0]?.reference_no || "";
      chequeDate.value = doc.payments?.[0]?.reference_date || chequeDate.value;
      // A part cheque: its amount, and the modes paying the rest.
      const rest = doc.payments?.slice(1) ?? [];
      if (rest.length && doc.payments?.[0]?.amount != null) {
        chequeAmount.value = Number(doc.payments[0].amount);
        chequeExtra.value = rest.map((p) => ({
          mode: p.mode_of_payment,
          amount: p.amount ?? null,
          reference: p.reference_no ?? "",
        }));
      }
    }
    loyalty.value = doc.write_off_amount || null;
    orderAdvance.value = Number(doc.total_advance) || 0;
    // A cash draft with a delivery person and no payment stored is left for them to collect.
    driver.value = paymentType.value === "cash" ? doc.driver || "" : "";
    driverCollects.value = !doc.is_pos && !doc.payments?.length;
    // A single partial payment on a draft: show its amount.
    if (doc.payments?.length === 1 && doc.payments[0].amount != null
        && Math.abs(Number(doc.payments[0].amount) - Number(doc.grand_total)) > 0.005) {
      singleAmount.value = Number(doc.payments[0].amount);
    }
    if (doc.payments?.length && paymentType.value === "cash") {
      payRows.value = doc.payments.map((p) => ({
        mode: p.mode_of_payment,
        amount: p.amount ?? null,
        reference: p.reference_no ?? "",
      }));
    }
    // Rebuild line rows with the rates, UOM and factor they were saved with;
    // the item's other UOMs are loaded below so the UOM can still change.
    lines.value = doc.items.map<Line>((it) => ({
      item_code: it.item_code,
      item_name: it.item_name,
      qty: it.qty,
      // ERPNext's rate is already after the line discount; the form applies
      // the discount % to `rate`, so start from the rate before it (a desk /
      // pricing-rule draft was discounted twice and under-billed).
      rate: rateBeforeDiscount(it.rate, it.discount_percentage, it.price_list_rate),
      price_list_rate: it.price_list_rate,
      discount_percentage: it.discount_percentage,
      discount_amount: it.discount_amount,
      uom: it.uom ?? undefined,
      // The saved factor, not 1: the server stores what we send, so 1 made a
      // Carton line move a single piece of stock.
      conversion_factor: it.conversion_factor ?? 1,
      warehouse: it.warehouse ?? undefined,
      price_list: it.price_list ?? null,
      uoms: it.uom
        ? [{ uom: it.uom, conversion_factor: it.conversion_factor ?? 1, price_list_rate: it.price_list_rate }]
        : [],
      amount: it.amount,
    }));
    void loadDraftUoms();
    void loadDraftMinRates();
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
    void router.replace({ name: "invoices" });
  }
}

/** Minimum rates for an edited draft's lines (a draft line doesn't carry them). */
async function loadDraftMinRates() {
  await Promise.all(
    lines.value.map(async (l) => {
      try {
        const p = await priceFor(l.item_code, customer.value || undefined, l.uom, l.price_list);
        l.min_rate = p.min_rate ?? undefined;
      } catch {
        /* offline: the server still checks on save */
      }
    }),
  );
}

/** The item UOMs of an edited draft's lines (a draft line only knows its
 *  own), so the UOM can be changed as on a new line. Saved rates stay until
 *  the UOM is changed; offline, a line keeps its one UOM. */
async function loadDraftUoms() {
  if (!session.uomChangeAllowed) return;
  const codes = [...new Set(lines.value.map((l) => l.item_code))];
  await Promise.all(
    codes.map(async (code) => {
      let uoms = uomCache[uomKey(code)];
      if (!uoms) {
        try {
          uoms = (await itemDetail(code, customer.value || undefined)).uoms;
          uomCache[uomKey(code)] = uoms;
        } catch {
          return;
        }
      }
      for (const l of lines.value) {
        if (l.item_code !== code) continue;
        const own = l.uoms?.[0];
        l.uoms = own && !uoms.some((u) => u.uom === own.uom) ? [own, ...uoms] : uoms;
      }
    }),
  );
}

async function searchItems() {
  // Same rule as the first load: an order taker searches the whole catalog.
  items.value = await listItems(itemSearch.value || undefined, warehouse.value || undefined, 80, session.updateStock);
}

/** Round to the site's currency precision (floats give 248.39999999999998). */
function round(n: number): number {
  const f = 10 ** session.currencyPrecision;
  return Math.round((Number(n) || 0) * f) / f;
}
const money = (n: number) => (Number(n) || 0).toFixed(session.currencyPrecision);
/** Rates keep Sales Invoice Item.rate's precision (may differ from amounts). */
function roundRate(n: number): number {
  const f = 10 ** session.ratePrecision;
  return Math.round((Number(n) || 0) * f) / f;
}
const rateText = (n: number) => (Number(n) || 0).toFixed(session.ratePrecision);

/** A past price tapped under the line: it becomes the line's rate (as sold, so no line discount on top). */
function usePrice(l: Line, rate: number) {
  l.rate = roundRate(rate);
  l.discount_percentage = 0;
  recalc(l);
}

function recalc(l: Line) {
  const qty = Number(l.qty) || 0;
  const rate = Number(l.rate) || 0;
  const disc = session.lineDiscount ? Number(l.discount_percentage) || 0 : 0;
  // ERPNext rounds the discounted rate to the rate precision before the
  // amount; doing the same keeps the preview (and a "rest" payment) exact.
  const net = qty * roundRate(rate * (1 - disc / 100));
  l.amount = round(Math.max(0, net));
}

/** Catalog pick: add the line and, after a search, clear it (full list back,
 *  cursor in the box) so the next item can be typed straight away. */
const itemSearchEl = ref<HTMLInputElement | null>(null);
async function pickItem(it: ItemRow) {
  const before = lines.value.length;
  await addLine(it);
  if (lines.value.length > before && itemSearch.value) {
    itemSearch.value = "";
    void searchItems();
    itemSearchEl.value?.focus();
  }
}

async function addLine(item: ItemRow) {
  insight.noteStock(item);
  // Always add a new row (same-item multi-row per PDF 1a).
  let uoms = uomCache[uomKey(item.item_code)];
  // No price from the price list → 0, as in ERPNext; the driver types it.
  let priceListRate = 0;
  if (!uoms) {
    try {
      const d = await itemDetail(item.item_code, customer.value || undefined);
      uoms = d.uoms;
      priceListRate = d.price_list_rate || priceListRate;
      uomCache[uomKey(item.item_code)] = uoms;
    } catch {
      uoms = [
        {
          uom: item.stock_uom,
          conversion_factor: 1,
          price_list_rate: 0,
        },
      ];
    }
  } else {
    // Pick the stock_uom entry for price seed.
    const match = uoms.find((u) => u.uom === item.stock_uom) ?? uoms[0];
    priceListRate = match?.price_list_rate || priceListRate;
  }
  // The server lists the item's Sales UOM first. When UOM change is off the
  // line must sell in the stock UOM (the UOM field is read-only then).
  const firstUom = session.uomChangeAllowed
    ? uoms[0]
    : (uoms.find((u) => u.uom === item.stock_uom) ?? uoms[0]);
  const line: Line = {
    item_code: item.item_code,
    item_name: item.item_name,
    qty: 1,
    rate: roundRate(firstUom?.price_list_rate || priceListRate),
    price_list_rate: roundRate(firstUom?.price_list_rate || priceListRate),
    uom: firstUom?.uom || item.stock_uom,
    conversion_factor: firstUom?.conversion_factor || 1,
    discount_percentage: 0,
    warehouse: warehouse.value || undefined,
    uoms,
    amount: 0,
    min_rate: firstUom?.min_rate,
  };
  recalc(line);
  lines.value.push(line);
}

async function onUomChange(l: Line) {
  if (!l.uoms) return;
  // The UOM choices carry the document list's prices; a line on its own list asks the server.
  const chosen = l.price_list ? undefined : l.uoms.find((u) => u.uom === l.uom);
  if (chosen) {
    l.conversion_factor = chosen.conversion_factor;
    l.price_list_rate = roundRate(chosen.price_list_rate);
    l.rate = roundRate(chosen.price_list_rate);
    l.min_rate = chosen.min_rate;
  } else {
    try {
      const p = await priceFor(l.item_code, customer.value || undefined, l.uom, l.price_list);
      l.price_list_rate = roundRate(p.price_list_rate);
      l.rate = roundRate(p.price_list_rate);
      l.min_rate = p.min_rate ?? undefined;
    } catch {
      /* keep existing rate */
    }
  }
  recalc(l);
}

/** Steel Force: price a line from another of the branch's lists (an offer
 *  list), as the desk's per-row Price List. A list without a price for the
 *  item leaves the rate as it is; its minimum still applies. */
async function onPriceListChange(l: Line) {
  try {
    const p = await priceFor(l.item_code, customer.value || undefined, l.uom, l.price_list);
    l.min_rate = p.min_rate ?? undefined;
    if (p.price_list_rate) {
      l.price_list_rate = roundRate(p.price_list_rate);
      l.rate = roundRate(p.price_list_rate);
    } else {
      toasts.warn(`${l.item_name || l.item_code} has no price in ${l.price_list || "the default list"}`);
    }
    recalc(l);
  } catch (e) {
    toasts.warn(e instanceof Error ? e.message : String(e));
  }
}

function removeLine(idx: number) {
  lines.value.splice(idx, 1);
}

async function doSave(submit: 0 | 1) {
  if (busy.value || savingDraft.value) return;
  if (!customer.value) { toasts.warn("Pick a customer"); return; }
  if (lines.value.length === 0) { toasts.warn("Add at least one item"); return; }
  const zeroQty = lines.value.find((l) => !(Number(l.qty) > 0));
  if (zeroQty) { toasts.warn(`Enter a quantity for ${zeroQty.item_name || zeroQty.item_code}`); return; }
  {
    // Steel Force: a customer awaiting approval, or credit / cheque offline.
    const blocked = submit === 1
      ? saleBlock(credit.value, paymentType.value, { online: isOnline(), steelforce: session.steelforce })
      : null;
    if (blocked) { toasts.warn(blocked, 6000); return; }
  }
  if (paymentType.value === "cheque" && (!chequeNo.value.trim() || !chequeDate.value)) {
    toasts.warn("Enter the cheque number and date");
    return;
  }
  if (paymentType.value === "cheque") {
    if (chequePart.value <= 0.005) { toasts.warn("Enter the cheque amount"); return; }
    if (chequeShort.value < -0.005) { toasts.warn("Payments are more than the amount to pay"); return; }
    if (chequeShort.value > 0.005) {
      toasts.warn(`${money(chequeShort.value)} is not paid yet: add a payment mode for it`);
      return;
    }
  }
  if (loyaltyAmount.value > 0 && session.loyalty && loyaltyAmount.value > session.loyalty.max + 0.0001) {
    toasts.warn(`Loyalty can be at most ${money(session.loyalty.max)}`);
    return;
  }
  const low = lines.value.find(belowMin);
  if (low) {
    toasts.warn(`${low.item_name || low.item_code}: the lowest rate allowed is ${rateText(low.min_rate ?? 0)}`);
    return;
  }
  if (useSplit.value) {
    if (!payRows.value.length) { toasts.warn("Add a payment, or choose Credit"); return; }
    if (splitCredit.value < -0.005) { toasts.warn("Payments are more than the invoice total"); return; }
  } else if (paymentType.value === "cash" && !collectLater.value && singleAmount.value != null) {
    if (singleAmount.value <= 0) { toasts.warn("Enter the amount paid, or choose Credit"); return; }
    if (singleAmount.value > toPay.value + 0.005) { toasts.warn("Amount is more than the amount to pay"); return; }
  }
  if (paymentType.value === "cash" && pickedDriver.value?.blocked) {
    toasts.warn(`${pickedDriver.value.full_name} can't take a cash sale: ${pickedDriver.value.blocked}`);
    return;
  }
  const flag = submit === 1;
  // Lock the buttons from the first tap: the pre-check and the confirm take a
  // moment, and a second tap meanwhile submitted a second invoice.
  if (flag) busy.value = true; else savingDraft.value = true;
  if (flag) {
    const go = await precheckBeforeSubmit(
      "Sales Invoice",
      customer.value,
      paymentType.value,
      lines.value.map((l) => ({
        item_code: l.item_code,
        item_name: l.item_name,
        rate: effectiveRate(l),
        // The minimum price is checked after the invoice discount (sf_trading).
        net_rate: effectiveRate(l) * netRateFactor(netTotal.value, totals.value),
        conversion_factor: l.conversion_factor,
        price_list: l.price_list || null,
      })),
      { amount: unpaidPart.value, fromOrder: fromOrder.value },
    );
    if (!go) { busy.value = false; return; }
    const paid = useSplit.value
      ? splitPaid.value
      : paymentType.value === "cash" && !collectLater.value ? singleAmount.value ?? grandTotal.value : 0;
    const pay = paymentType.value === "cheque"
      ? [
          `Cheque ${chequeNo.value} · ${chequeDate.value}`,
          chequeRestRows().length
            ? [`${money(chequePart.value)} cheque`, ...chequeRestRows().map((r) => `${money(r.amount)} ${r.mode_of_payment}`)].join(" + ")
            : "",
          loyaltyAmount.value ? `loyalty ${money(loyaltyAmount.value)}` : "",
        ].filter(Boolean).join(" · ")
      : collectLater.value
      ? `Cash · ${driverName.value} collects on delivery`
      : paid <= 0.005
      ? "Credit"
      : paid >= toPay.value - 0.005
      ? `Paid in full${loyaltyAmount.value ? ` · loyalty ${money(loyaltyAmount.value)}` : ""}`
      : `Paid ${money(paid)} · rest on credit`;
    const ok = await confirmSubmit(isEditMode.value ? "Submit this invoice?" : "Submit invoice?", [
      selectedCustomer.value ? customerLabel(selectedCustomer.value) : customer.value,
      `${lines.value.length} item${lines.value.length === 1 ? "" : "s"} · ${withCurrency(money(grandTotal.value))}`,
      pay,
    ]);
    if (!ok) { busy.value = false; return; }
  }
  try {
    // The invoice discount goes to ERPNext as its Additional Discount
    // (discount_amount + apply_discount_on from Vansale Settings), so item
    // rates stay as sold and ERPNext / ZATCA see a document-level discount.
    const docDisc = Math.max(0, Number(discountAmount.value) || 0);

    const payload = {
      customer: customer.value,
      warehouse: warehouse.value || undefined,
      // A line discount % (when allowed) goes into the line's `rate`; ERPNext
      // derives discount_percentage / discount_amount from
      // (price_list_rate - rate), which survives submit.
      items: lines.value.map<InvoiceItem>((l) => {
        // The rate the driver sees (and may have typed) is the base. Using
        // price_list_rate here silently replaced a typed rate with the list
        // price: the screen showed one total and the invoice posted another.
        const listRate = Number(l.price_list_rate) || 0;
        const baseRate = Number(l.rate) || listRate;
        const linePct = session.lineDiscount ? Math.max(0, Math.min(100, Number(l.discount_percentage) || 0)) : 0;
        const effectiveRate = roundRate(Math.max(0, baseRate * (1 - linePct / 100)));
        return {
          item_code: l.item_code,
          item_name: l.item_name,
          qty: l.qty,
          rate: effectiveRate,
          // Below the list price → ERPNext records the difference as a
          // discount. Above it → send the typed rate as the list price, since a
          // rate above price_list_rate makes ERPNext add a margin that grows
          // on every save.
          price_list_rate: Math.max(listRate, baseRate),
          // Do NOT send discount_percentage / discount_amount — let ERPNext
          // derive both from (price_list_rate - rate) so the stored values
          // survive submit (its on_submit recalc overrides stamps we send).
          uom: l.uom,
          conversion_factor: l.conversion_factor,
          warehouse: l.warehouse,
          price_list: l.price_list || undefined,
        };
      }),
      remarks: remarks.value || undefined,
      update_stock: session.updateStock ? (1 as const) : (0 as const),
      collect_later: collectLater.value ? (1 as const) : (0 as const),
      submit,
      payment_type: paymentType.value,
      mode_of_payment:
        paymentType.value === "cheque"
          ? chequeMode.value
          : paymentType.value === "cash" && !collectLater.value ? modeOfPayment.value : undefined,
      cheque_no: paymentType.value === "cheque" ? chequeNo.value.trim() : undefined,
      cheque_date: paymentType.value === "cheque" ? chequeDate.value : undefined,
      cheque_amount: paymentType.value === "cheque" && chequeRestRows().length ? chequePart.value : undefined,
      write_off_amount: loyaltyAmount.value > 0 ? loyaltyAmount.value : undefined,
      driver: session.askDriver && paymentType.value === "cash" ? driver.value : undefined,
      payments: paymentType.value === "cheque"
        ? chequeRestRows().length ? chequeRestRows() : undefined
        : useSplit.value
        ? payRows.value.map((r) => ({
            mode_of_payment: r.mode,
            amount: r.amount == null || (r.amount as unknown) === "" ? null : Number(r.amount),
            reference_no: r.reference || null,
          }))
        : paymentType.value === "cash" && !collectLater.value && singleAmount.value != null
          // Partial payment in one mode; untouched = full amount (server pays the exact total).
          ? [{ mode_of_payment: modeOfPayment.value, amount: singleAmount.value, reference_no: null }]
          : undefined,
      // 0 on an edited draft clears an earlier discount; the server applies
      // it on the "Apply additional discount on" setting.
      discount_amount: docDisc > 0 ? docDisc : isEditMode.value ? 0 : undefined,
      apply_discount_on: docDisc > 0 ? session.applyDiscountOn : undefined,
    };
    // Edit mode uses server-side `update_draft` which mutates the existing
    // doc in place — Van Users have write perm on their own drafts but NOT
    // delete perm, so the previous delete-then-save flow always raised
    // "Insufficient Permission for Sales Invoice". Keep the same payload
    // shape; `updateDraft` swaps the endpoint.
    const res = isEditMode.value
      ? await updateDraft({
          name: editName.value,
          items: payload.items,
          remarks: payload.remarks,
          warehouse: payload.warehouse,
          submit: payload.submit,
          payment_type: payload.payment_type,
          mode_of_payment: payload.mode_of_payment,
          payments: payload.payments,
          collect_later: payload.collect_later,
          cheque_no: payload.cheque_no,
          cheque_date: payload.cheque_date,
          cheque_amount: payload.cheque_amount,
          write_off_amount: payload.write_off_amount,
          driver: payload.driver,
          discount_amount: payload.discount_amount,
          apply_discount_on: payload.apply_discount_on,
        })
      : await save(payload);
    toasts.success(
      res.queued
        ? "Saved offline — will sync when online"
        : `Invoice ${res.name} ${flag ? "submitted" : isEditMode.value ? "updated" : "saved as draft"} (${session.currency} ${money(res.grand_total)})`,
    );
    lines.value = [];
    // Always land on the detail view after a successful save/submit so the
    // user can see the QR, tax breakup and hit Print manually. The old flow
    // auto-opened a `window.open` print popup (hostile on the Capacitor
    // WebView — it maps `_blank` to the host browser) and then bounced to
    // the dashboard on the queued path, which felt like "submit = home".
    if (!res.queued && res.name && !res.name.startsWith("QUEUED")) {
      // "Print after submit": the detail view prints on arrival.
      const autoprint = flag && session.printBehaviour?.after_submit ? { autoprint: "1" } : undefined;
      void router.push({ name: "invoice-detail", params: { name: res.name }, query: autoprint });
    } else {
      // Queued offline — no real doc name, so the detail page can't resolve.
      void router.push({ name: "invoices" });
    }
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof Error ? e.message : String(e),
    );
  } finally {
    busy.value = false;
    savingDraft.value = false;
  }
}

// "New customer" in the middle of a sale: the cart is kept and put back when
// the form opens again with the new customer (it used to be lost).
const CART_KEY = "vansale.invoice.cart";
function newCustomerClick() {
  if (lines.value.length) {
    try {
      sessionStorage.setItem(CART_KEY, JSON.stringify({
        at: Date.now(),
        lines: lines.value,
        paymentType: paymentType.value,
        discountAmount: discountAmount.value,
        remarks: remarks.value,
      }));
    } catch { /* storage full / blocked: the cart is simply not kept */ }
  }
  router.push({ name: "customer-new", query: { redirect: "invoice" } });
}
function restoreCart() {
  try {
    const raw = sessionStorage.getItem(CART_KEY);
    sessionStorage.removeItem(CART_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw) as { at: number; lines: Line[]; paymentType?: typeof paymentType.value; discountAmount?: number | null; remarks?: string };
    if (!saved.lines?.length || Date.now() - saved.at > 2 * 3600_000) return;
    lines.value = saved.lines;
    if (saved.paymentType) paymentType.value = saved.paymentType;
    discountAmount.value = saved.discountAmount ?? null;
    remarks.value = saved.remarks ?? "";
    toasts.info("Your cart was kept for the new customer");
  } catch { /* a stale or broken copy is ignored */ }
}

onMounted(loadAll);
</script>

<template>
  <div class="stack form-split">
    <!-- Customer -->
    <section class="card stack">
      <div class="row-head">
        <span class="label">Customer</span>
        <button type="button" class="link-btn" @click="newCustomerClick">
          <Icon name="plus" :size="14" /> New
        </button>
      </div>
      <!-- A draft keeps its customer (the server doesn't change it on edit). -->
      <SearchSelect
        v-model="customer"
        :options="customerOptions"
        placeholder="Search customer by name or code"
        remote
        :disabled="isEditMode"
        @search="onCustomerSearch"
      />
      <div v-if="selectedCustomer" class="selected-hint">
        <Icon name="customer" :size="14" /> {{ customerLabel(selectedCustomer) }}
      </div>
      <div v-if="warehouse" class="muted small">
        <Icon name="truck" :size="14" /> {{ warehouse }}
      </div>
      <div v-if="session.$state.defaults?.sales_person_name" class="sp-chip">
        <Icon name="user" :size="12" /> Sales: {{ session.$state.defaults.sales_person_name }}
      </div>
    </section>

    <!-- Payment -->
    <section class="card stack">
      <span class="label">Payment</span>
      <div class="seg">
        <button
          type="button"
          class="seg-btn"
          :data-active="paymentType === 'cash'"
          @click="pickPayment('cash')"
        >
          <Icon name="payment" :size="16" /> Cash
        </button>
        <button
          type="button"
          class="seg-btn"
          :data-active="paymentType === 'credit'"
          :data-blocked="Boolean(refusalFor('credit'))"
          @click="pickPayment('credit')"
        >
          <Icon :name="refusalFor('credit') ? 'alert' : 'clock'" :size="16" /> Credit
        </button>
        <button
          v-if="chequeMops.length || paymentType === 'cheque'"
          type="button"
          class="seg-btn"
          :data-active="paymentType === 'cheque'"
          :data-blocked="Boolean(refusalFor('cheque'))"
          @click="pickPayment('cheque')"
        >
          <Icon :name="refusalFor('cheque') ? 'alert' : 'receipt'" :size="16" /> Cheque
        </button>
      </div>
      <CreditPanel
        v-if="customer"
        :status="credit"
        :loading="creditLoading"
        :payment="paymentType"
        :adds="unpaidPart"
      />
      <div v-if="paymentType === 'cheque'" class="cheque-card">
        <div class="cheque-head">
          <span class="cheque-title"><Icon name="receipt" :size="16" /> Cheque</span>
          <span v-if="chequeDaysAhead > 0" class="pill" data-tone="info">
            Post-dated · banked in {{ chequeDaysAhead }} day{{ chequeDaysAhead === 1 ? "" : "s" }}
          </span>
          <span v-else class="pill" data-tone="success">Dated today</span>
        </div>
        <div class="cheque-fields">
          <label class="field">
            <span class="tiny">Cheque no. *</span>
            <input type="text" v-model="chequeNo" inputmode="numeric" placeholder="e.g. 004512"
                   :class="{ missing: !chequeNo.trim() }" />
          </label>
          <label class="field">
            <span class="tiny">Cheque date</span>
            <input type="date" v-model="chequeDate" />
          </label>
        </div>
        <!-- Same as a split cash sale: the cheque, then other modes for the rest. -->
        <div class="pay-rows">
          <div class="pay-row">
            <select v-if="chequeMops.length > 1" v-model="chequeMode" aria-label="Cheque mode">
              <option v-for="m in chequeMops" :key="m.name" :value="m.name">{{ m.name }}</option>
            </select>
            <span v-else class="mode-fixed"><Icon name="receipt" :size="14" /> {{ chequeMode || "Cheque" }}</span>
            <input type="number" min="0" step="any" inputmode="decimal" v-model.number="chequeAmount"
                   v-decimals="session.currencyPrecision" :placeholder="chequeHint(0)" aria-label="Cheque amount"
                   @focus="fillChequeRest(0)" />
            <!-- Keeps the amounts in one column with the rows that have a remove button. -->
            <button v-if="chequeExtra.length" class="icon-only small rm-space" type="button" tabindex="-1" aria-hidden="true">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div v-for="(r, i) in chequeExtra" :key="i" class="pay-row">
            <select v-model="r.mode">
              <option v-for="m in restMops" :key="m.name" :value="m.name">{{ m.name }}</option>
            </select>
            <input type="number" min="0" step="any" inputmode="decimal" v-model.number="r.amount"
                   v-decimals="session.currencyPrecision" :placeholder="chequeHint(i + 1)" @focus="fillChequeRest(i + 1)" />
            <button class="icon-only small" type="button" @click="chequeExtra.splice(i, 1)" aria-label="Remove">
              <Icon name="x" :size="16" />
            </button>
            <input v-if="needsReference(r.mode)" class="pay-ref" type="text" v-model="r.reference"
                   placeholder="Reference no. (optional)" />
          </div>
          <button v-if="canAddChequeRow" type="button" class="link-btn" @click="addChequeRow">
            <Icon name="plus" :size="14" /> Add payment mode
          </button>
          <div v-if="chequeExtra.length" class="tot-row small">
            <span>Paid</span>
            <span class="tabular"><SarSymbol :code="session.currency" />{{ money(chequePaid) }}</span>
          </div>
          <div v-if="Math.abs(chequeShort) > 0.005" class="tot-row small short">
            <span>{{ chequeShort > 0 ? "Not paid yet" : "More than the amount to pay" }}</span>
            <span class="tabular"><SarSymbol :code="session.currency" />{{ money(Math.abs(chequeShort)) }}</span>
          </div>
        </div>
        <p v-if="chequeDaysAhead > 0" class="muted xsmall hint">Until it can be banked, it counts as credit.</p>
      </div>
      <!-- Only when the branch has delivery persons: an empty picker is just noise. -->
      <label v-if="session.askDriver && paymentType === 'cash' && driverList.length" class="field">
        <span class="tiny">Delivery person</span>
        <select v-model="driver" @change="onDriverPicked">
          <option value="">No delivery person</option>
          <option v-for="d in driverList" :key="d.name" :value="d.name" :disabled="Boolean(d.blocked) && d.name !== driver">
            {{ d.full_name }}{{ d.blocked ? ` — ${d.blocked}` : "" }}
          </option>
        </select>
      </label>
      <p v-if="pickedDriver && (pickedDriver.holding ?? 0) > 0" class="muted xsmall driver-cash">
        {{ pickedDriver.full_name }} holds <SarSymbol :code="session.currency" />{{ money(pickedDriver.holding ?? 0) }}
        not yet handed in<template v-if="pickedDriver.cash_limit"> (limit {{ money(pickedDriver.cash_limit) }})</template>.
      </p>
      <p v-if="pickedDriver?.blocked" class="small bad-note">
        {{ pickedDriver.full_name }} can't take a cash sale: {{ pickedDriver.blocked }}. Collect from them first, or pick another.
      </p>
      <div v-if="paymentType === 'cash' && driver" class="seg seg-small">
        <button type="button" class="seg-btn" :data-active="driverCollects" @click="driverCollects = true">
          Collect on delivery
        </button>
        <button type="button" class="seg-btn" :data-active="!driverCollects" @click="driverCollects = false">
          Paid now
        </button>
      </div>
      <p v-if="collectLater" class="muted small later-note">
        Not paid now — {{ driverName }} collects the cash on delivery. The invoice stays unpaid until it is handed in.
      </p>
      <div v-if="useSplit" class="pay-rows">
        <div v-for="(r, i) in payRows" :key="i" class="pay-row">
          <select v-model="r.mode">
            <option v-for="m in mops" :key="m.name" :value="m.name">{{ m.name }}</option>
          </select>
          <input type="number" min="0" step="any" inputmode="decimal" v-model.number="r.amount" v-decimals="session.currencyPrecision"
                 placeholder="Tap for rest" @focus="fillRest(i)" />
          <button v-if="payRows.length > 1" class="icon-only small" type="button" @click="removePayRow(i)" aria-label="Remove">
            <Icon name="x" :size="16" />
          </button>
          <input v-if="needsReference(r.mode)" class="pay-ref" type="text" v-model="r.reference"
                 placeholder="Reference no. (optional)" />
        </div>
        <button type="button" class="link-btn" @click="addPayRow">
          <Icon name="plus" :size="14" /> Add payment mode
        </button>
        <div class="tot-row small">
          <span>Paid</span>
          <span class="tabular"><SarSymbol :code="session.currency" />{{ money(splitPaid) }}</span>
        </div>
        <div v-if="splitCredit > 0" class="tot-row small muted">
          <span>On credit</span>
          <span class="tabular"><SarSymbol :code="session.currency" />{{ money(splitCredit) }}</span>
        </div>
      </div>
      <div v-else-if="paymentType === 'cash' && !collectLater" class="stack-sm">
        <div class="mode-amount">
          <label class="field">
            <span class="tiny">Mode of Payment</span>
            <select v-model="modeOfPayment">
              <option v-for="m in mops" :key="m.name" :value="m.name">{{ m.name }}</option>
              <option v-if="!mops.length" :value="modeOfPayment">{{ modeOfPayment }}</option>
            </select>
          </label>
          <label class="field">
            <span class="tiny">Amount</span>
            <input type="number" min="0" step="any" inputmode="decimal" v-model.number="singleAmountModel" v-decimals="session.currencyPrecision" />
          </label>
        </div>
        <div v-if="singleCredit > 0" class="tot-row small muted pay-credit">
          <span>On credit</span>
          <span class="tabular"><SarSymbol :code="session.currency" />{{ money(singleCredit) }}</span>
        </div>
      </div>
      <!-- Steel Force loyalty: a small amount written off when the customer pays
           now. Tucked behind a link until it is wanted. -->
      <template v-if="loyaltyAllowed">
        <button v-if="!loyaltyOpen && !loyaltyAmount" type="button" class="link-btn loyalty-add" @click="loyaltyOpen = true">
          <Icon name="plus" :size="14" /> Loyalty <span class="muted">(up to {{ money(session.loyalty?.max ?? 0) }})</span>
        </button>
        <div v-else class="loyalty-row">
          <span class="loyalty-label">
            <span>Loyalty</span>
            <span class="muted xsmall">up to <SarSymbol :code="session.currency" />{{ money(session.loyalty?.max ?? 0) }}</span>
          </span>
          <input type="number" min="0" step="any" inputmode="decimal" v-model.number="loyalty"
                 v-decimals="session.currencyPrecision" :placeholder="money(0)" aria-label="Loyalty" />
          <button type="button" class="icon-only small" aria-label="Remove loyalty" @click="loyalty = null; loyaltyOpen = false">
            <Icon name="x" :size="14" />
          </button>
        </div>
      </template>
      <div v-if="loyaltyAmount > 0 || orderAdvance > 0" class="pay-summary">
        <div class="pay-sum small muted">
          <span>Invoice total</span>
          <span class="tabular"><SarSymbol :code="session.currency" />{{ money(grandTotal) }}</span>
        </div>
        <div v-if="orderAdvance > 0" class="pay-sum small muted">
          <span>Advance paid on the order</span>
          <span class="tabular">−<SarSymbol :code="session.currency" />{{ money(orderAdvance) }}</span>
        </div>
        <div v-if="loyaltyAmount > 0" class="pay-sum small muted">
          <span>Loyalty</span>
          <span class="tabular">−<SarSymbol :code="session.currency" />{{ money(loyaltyAmount) }}</span>
        </div>
        <div class="pay-sum pay-due">
          <span>Customer pays</span>
          <strong class="tabular"><SarSymbol :code="session.currency" />{{ money(toPay) }}</strong>
        </div>
      </div>
    </section>

    <!-- Lines -->
    <section class="card stack">
      <div class="section-head">
        <h3 style="margin:0">Lines</h3>
        <strong v-if="lines.length > 0" class="tabular">
          <SarSymbol :code="session.currency" />{{ money(netTotal) }}
        </strong>
      </div>
      <div v-if="lines.length === 0" class="empty" style="padding:1rem 0">
        <Icon name="bag" :size="28" class="empty-icon" />
        <span>Add items from the catalog.</span>
      </div>
      <ul v-else class="lines">
        <li v-for="(l, i) in lines" :key="i" class="line">
          <div class="line-head">
            <strong class="truncate">{{ l.item_name || l.item_code }}</strong>
            <button class="icon-only small" type="button" @click="removeLine(i)" aria-label="Remove">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="muted xsmall">{{ l.item_code }}</div>
          <div class="line-grid" :class="{ 'no-disc': !session.lineDiscount }">
            <label>
              <span class="tiny">Qty</span>
              <input type="number" min="0" step="any" inputmode="decimal"
                     v-model.number="l.qty" @input="recalc(l)" />
            </label>
            <label>
              <span class="tiny">UOM</span>
              <select
                v-if="session.uomChangeAllowed && l.uoms && l.uoms.length > 1"
                v-model="l.uom"
                @change="onUomChange(l)"
              >
                <option v-for="u in l.uoms" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
              </select>
              <input v-else type="text" :value="l.uom" disabled />
            </label>
            <label>
              <span class="tiny">Rate</span>
              <input type="number" min="0" step="any" inputmode="decimal" :class="{ 'below-min': belowMin(l) }"
                     v-model.number="l.rate" v-decimals="session.ratePrecision" @input="recalc(l)" />
            </label>
            <label v-if="session.lineDiscount">
              <span class="tiny">Disc %</span>
              <input type="number" min="0" max="100" step="any" inputmode="decimal"
                     v-model.number="l.discount_percentage" @input="recalc(l)" />
            </label>
          </div>
          <label v-if="session.rowPriceLists.length > 1" class="row-pl">
            <span class="tiny">Price list</span>
            <select v-model="l.price_list" @change="onPriceListChange(l)">
              <option :value="null">Usual list</option>
              <option v-for="pl in session.rowPriceLists" :key="pl" :value="pl">{{ pl }}</option>
            </select>
          </label>
          <LineInsight :item-code="l.item_code" :customer="customer" :uom="l.uom"
                       :conversion-factor="l.conversion_factor" :last="insight.lastSale(l.item_code)"
                       :short="insight.shortage(l)" @use="(r: number) => usePrice(l, r)" />
          <div class="line-foot">
            <span v-if="l.price_list_rate && l.price_list_rate !== l.rate" class="muted xsmall">
              List: <SarSymbol :code="session.currency" />{{ rateText(l.price_list_rate || 0) }}
            </span>
            <span v-if="l.min_rate" class="xsmall" :class="belowMin(l) ? 'min-low' : 'muted'">
              Min: <SarSymbol :code="session.currency" />{{ rateText(l.min_rate) }}
            </span>
            <strong class="tabular"><SarSymbol :code="session.currency" />{{ money(l.amount) }}</strong>
          </div>
        </li>
      </ul>
    </section>

    <!-- Catalog -->
    <section class="card stack split-side">
      <h3 style="margin:0">Catalog</h3>
      <div class="search-bar">
        <Icon name="search" :size="18" class="search-ic" />
        <input ref="itemSearchEl" :value="itemSearch" placeholder="Search item code / name / barcode" @input="itemSearch = inputValue($event); searchItems()" @focus="revealOnFocus" />
      </div>
      <ul class="catalog">
        <li v-for="it in items" :key="it.item_code">
          <button class="cat-item" type="button" @click="pickItem(it)">
            <div>
              <strong class="truncate">{{ it.item_name }}</strong>
              <div class="muted xsmall">{{ it.item_code }}</div>
            </div>
            <div class="right-col">
              <span v-if="typeof it.stock_qty === 'number' && it.is_stock_item !== 0" class="pill" data-tone="primary">
                {{ stockLabel(it.stock_qty, it.stock_uom, it.sales_uom, it.sales_cf) }}
              </span>
            </div>
          </button>
        </li>
      </ul>
      <!--
        The catalog is filtered to items the van actually carries, so an
        empty list is a stock problem, not a broken screen. Say which, or
        the driver reads a blank panel as "the app is down".
      -->
      <p v-if="items.length === 0" class="muted small">{{ emptyCatalogHint }}</p>
    </section>

    <!-- Totals preview -->
    <section v-if="lines.length > 0" class="card stack totals">
      <div class="tot-row">
        <span>Net total</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ money(netTotal) }}</span>
      </div>
      <label class="field">
        <span class="tiny">Additional discount on {{ session.applyDiscountOn }} ({{ session.currency }})</span>
        <input type="number" min="0" step="any" inputmode="decimal" v-model.number="discountAmount" v-decimals="session.currencyPrecision" placeholder="0" />
      </label>
      <div class="tot-row muted">
        <span>
          {{ tax.taxes[0]?.description || "VAT" }} ({{ tax.rate.toFixed(tax.rate % 1 ? 2 : 0) }}%)
          <em v-if="tax.inclusive" class="incl">incl.</em>
        </span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ money(taxTotal) }}</span>
      </div>
      <div class="tot-row grand">
        <span>Grand total</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ money(grandTotal) }}</span>
      </div>
      <div v-if="tax.inclusive" class="tot-row muted small">
        <span>Net of tax</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ money(netOfTax) }}</span>
      </div>
      <p v-if="!tax.simple" class="muted xsmall">
        This tax template has compound rows — the preview is approximate. The
        server computes the exact breakup on save.
      </p>
    </section>

    <label class="field">
      <span class="label">Notes (optional)</span>
      <textarea v-model="remarks" rows="2" />
    </label>

    <div class="actions">
      <button class="btn-ghost" type="button"
              :disabled="savingDraft || busy || lines.length === 0"
              @click="doSave(0)">
        <Icon name="edit" :size="18" />
        {{ savingDraft ? "Saving…" : "Save draft" }}
      </button>
      <button class="submit" type="button"
              :disabled="busy || savingDraft || lines.length === 0"
              @click="doSave(1)">
        <Icon name="check" :size="18" />
        {{ busy ? "Submitting…" : `Submit · ${session.currency} ${money(grandTotal)}` }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.row-head { display: flex; justify-content: space-between; align-items: center; }
.link-btn {
  all: unset; cursor: pointer; color: var(--primary);
  font-size: var(--text-xs); font-weight: 600;
  display: inline-flex; align-items: center; gap: 0.25rem;
}
.selected-hint { font-size: var(--text-xs); color: var(--primary); display: inline-flex; align-items: center; gap: 0.3rem; }
.sp-chip {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: var(--text-xs); color: var(--text-muted);
  background: var(--surface-muted); padding: 0.2rem 0.5rem;
  border-radius: 999px; width: fit-content;
}

.seg { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 0.5rem; }
.pay-rows { display: flex; flex-direction: column; gap: 0.5rem; }
.mode-amount { display: grid; grid-template-columns: 1fr 8rem; gap: 0.5rem; }
.stack-sm { display: flex; flex-direction: column; gap: 0.4rem; }
.pay-credit { display: flex; justify-content: space-between; align-items: center; }
.pay-row { display: grid; grid-template-columns: 1fr 7rem auto; gap: 0.4rem; align-items: center; }
.pay-ref { grid-column: 1 / -1; }
.pay-rows .tot-row { display: flex; justify-content: space-between; align-items: center; }
.pay-sum { display: flex; justify-content: space-between; align-items: center; }
.seg-btn {
  all: unset; cursor: pointer;
  padding: 0.55rem 0.75rem; border-radius: var(--radius-sm);
  background: var(--surface-muted); text-align: center;
  font-weight: 500; display: inline-flex; justify-content: center; align-items: center; gap: 0.35rem;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.seg-btn[data-active="true"] { background: var(--primary); color: var(--on-primary, white); }
/* Not allowed for this customer: still tappable (it says why), but looks off. */
.seg-btn[data-blocked="true"]:not([data-active="true"]) { color: var(--text-faint); }
.seg-btn[data-blocked="true"][data-active="true"] { background: var(--danger); }
.seg-small .seg-btn { min-height: 2.25rem; font-size: var(--text-sm); }
.below-min { border-color: var(--danger); color: var(--danger); }
/* Cheque: one card — the cheque's details, then (part cheque) a receipt-like split. */
.cheque-card {
  display: flex; flex-direction: column; gap: 0.6rem;
  padding: 0.75rem; border-radius: var(--radius);
  background: var(--surface-muted); border: 1px solid var(--border);
}
.cheque-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.cheque-title { display: inline-flex; align-items: center; gap: 0.35rem; font-weight: 600; }
.cheque-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.cheque-card input, .cheque-card select { background: var(--surface); }
/* The cheque row's mode when the branch has one cheque mode: shown, not picked. */
.mode-fixed {
  display: flex; align-items: center; gap: 0.35rem; min-width: 0;
  padding: 0.65rem 0.8rem; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface-sunk); color: var(--text-muted); font-weight: 500;
}
.rm-space { visibility: hidden; }
.pay-rows .short { color: var(--danger); font-weight: 600; }
.missing { border-color: var(--warning); }
.hint { margin: 0; }
.loyalty-add { align-self: flex-start; }
.loyalty-row {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.45rem 0.45rem 0.45rem 0.75rem; border-radius: var(--radius-sm); background: var(--surface-muted);
}
.loyalty-label { flex: 1; min-width: 0; display: flex; flex-direction: column; font-size: var(--text-sm); font-weight: 500; }
.loyalty-row input { flex: none; width: 7.5rem; text-align: end; background: var(--surface); }
.loyalty-row input { appearance: textfield; -moz-appearance: textfield; }
.loyalty-row input::-webkit-inner-spin-button, .loyalty-row input::-webkit-outer-spin-button { -webkit-appearance: none; margin: 0; }
.pay-summary {
  display: flex; flex-direction: column; gap: 0.25rem;
  padding: 0.6rem 0.7rem; border-radius: var(--radius-sm); background: var(--surface-muted);
}
.pay-due { font-size: var(--text-base); border-top: 1px solid var(--border-strong); padding-top: 0.3rem; }
.min-low { color: var(--danger); font-weight: 600; }
.later-note, .driver-cash { margin: 0; }
.bad-note { margin: 0; color: var(--danger); }

.section-head { display: flex; justify-content: space-between; align-items: center; }
.tabular { font-variant-numeric: tabular-nums; }

.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.line { background: var(--surface-muted); border-radius: var(--radius); padding: 0.65rem 0.75rem; display: flex; flex-direction: column; gap: 0.3rem; }
.line-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.line-grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0.4rem; align-items: end; margin-top: 0.3rem; }
.line-grid.no-disc { grid-template-columns: 1fr 1fr 1fr; }
.line-grid label { display: flex; flex-direction: column; gap: 0.15rem; }
.row-pl { display: grid; grid-template-columns: auto 1fr; gap: 0.5rem; align-items: center; }
.row-pl select { padding: 0.4rem 0.55rem; font-size: var(--text-sm); }
.line-grid input, .line-grid select { padding: 0.45rem 0.55rem; font-size: var(--text-sm); }
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.line-foot { display: flex; justify-content: space-between; align-items: center; padding-top: 0.25rem; border-top: 1px dashed var(--border-soft, rgba(0,0,0,.08)); }

.search-bar { position: relative; }
.search-ic { position: absolute; inset-inline-start: 0.7rem; top: 50%; transform: translateY(-50%); color: var(--text-faint); pointer-events: none; }
.search-bar input { padding-inline-start: 2.3rem; }

.catalog { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; max-height: 22rem; overflow-y: auto; padding-right: 0.25rem; }
.cat-item {
  all: unset; box-sizing: border-box; width: 100%; cursor: pointer;
  padding: 0.55rem 0.75rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
  transition: background var(--dur-fast) var(--ease);
}
.cat-item:active { background: var(--primary-soft); }
.right-col { display: flex; flex-direction: column; align-items: flex-end; gap: 0.2rem; }

.totals .tot-row { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); }
.totals .tot-row.grand { font-size: var(--text-base); font-weight: 700; border-top: 1px solid var(--border-soft, rgba(0,0,0,.08)); padding-top: 0.4rem; margin-top: 0.1rem; }

.warn { color: var(--warning); }

.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.actions { display: grid; grid-template-columns: 1fr 1.4fr; gap: 0.5rem; }
.btn-ghost {
  all: unset; cursor: pointer;
  min-height: 3.25rem; border-radius: var(--radius);
  background: var(--surface-muted); text-align: center;
  display: inline-flex; justify-content: center; align-items: center; gap: 0.4rem;
  font-weight: 600;
}
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.submit { min-height: 3.25rem; font-size: var(--text-base); }
.icon-only.small { min-height: 1.8rem; width: 1.8rem; padding: 0.3rem; }
/* Flags a tax-inclusive template so the driver knows the typed rate is gross. */
.incl {
  font-style: normal;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-soft);
  border-radius: var(--radius-pill);
  padding: 0.05rem 0.35rem;
  margin-inline-start: 0.25rem;
}

/* Landscape tablet: the catalog sits beside the form and stays in view, so
   adding items doesn't mean scrolling past the lines. Phones keep one column
   in the same order. */
@media (min-width: 1100px) {
  .form-split {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 24rem);
    column-gap: 1rem;
    row-gap: 0;
    align-items: start;
  }
  .form-split > * { grid-column: 1; margin-bottom: 0.75rem; }
  .form-split > .split-side {
    grid-column: 2;
    grid-row: 1 / span 12;
    position: sticky;
    top: calc(var(--top-bar-height) + 1rem);
  }
  .split-side .catalog {
    max-height: calc(100vh - var(--top-bar-height) - var(--bottom-nav-height) - 12rem);
  }
}
</style>
