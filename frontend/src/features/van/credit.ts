/**
 * What a customer's credit means for the sale on screen: whether Credit /
 * Cheque may be picked at all, and what this sale does to the limit.
 *
 * Pure functions (unit-tested); `useCreditStatus` loads the status for the
 * picked customer. The server runs every rule again on save, so this only
 * tells the salesman early — it never lets a sale through.
 */
import { ref, watch, type Ref } from "vue";
import { creditStatus, type CreditStatus } from "@/api/customer";

export type PayType = "cash" | "credit" | "cheque";

/** Why this payment type can't be used for the customer, or null. */
export function creditRefusal(s: CreditStatus | null | undefined, payment: PayType): string | null {
  if (!s || payment === "cash") return null;
  if (!s.credit_allowed) return s.credit_problem || "This customer buys for cash only.";
  // sf_trading refuses a Credit sale over an overdue credit invoice (a cheque is still allowed).
  if (payment === "credit" && s.blocking_overdue) {
    const o = s.blocking_overdue;
    return `Invoice ${o.name} of ${o.posting_date} is overdue (${Number(o.outstanding_amount).toFixed(2)} unpaid). No credit sale until it is paid.`;
  }
  return null;
}

/**
 * Why this sale can't go ahead at all, checked before anything is sent (it
 * also holds offline, on the saved credit status):
 *  - Steel Force: a customer waiting for approval gets no sale, cash included;
 *  - Steel Force: credit and cheque need a connection — sf_trading's credit
 *    rules can only be checked online, and a refusal at sync loses the sale.
 */
export function saleBlock(
  s: CreditStatus | null | undefined,
  payment: PayType | undefined,
  opts: { online: boolean; steelforce: boolean },
): string | null {
  const a = s?.approval;
  if (a?.covered && !a.approved) {
    return `Customer waiting for approval (${a.status || "Draft"}) — no sale until it is approved.`;
  }
  if (opts.steelforce && !opts.online && (payment === "credit" || payment === "cheque")) {
    return "Credit and cheque sales need a connection here: the credit rules are checked online. Sell for cash, or wait for the network.";
  }
  return null;
}

export interface CreditImpact {
  /** This sale counts against the limit (credit / cheque / unpaid part of cash). */
  counts: boolean;
  /** Steel Force: a cash sale never counts. */
  exempt: boolean;
  /** Used after this sale. */
  after: number;
  /** Available after this sale; null without a limit. */
  availableAfter: number | null;
  /** The sale takes the customer over the limit (ERPNext refuses it). */
  over: boolean;
  overBy: number;
  /** Same against the branch sub-limit (Steel Force). */
  branchOver: boolean;
}

/**
 * `adds`: the part of this sale left unpaid (the whole sale on credit / cheque,
 * the rest after a part payment, the whole order for an order).
 */
export function creditImpact(s: CreditStatus | null | undefined, payment: PayType | undefined, adds: number): CreditImpact {
  const none: CreditImpact = { counts: false, exempt: false, after: 0, availableAfter: null, over: false, overBy: 0, branchOver: false };
  if (!s) return none;
  const exempt = Boolean(s.cash_exempt) && payment === "cash";
  const amount = Math.max(Number(adds) || 0, 0);
  const counts = !exempt && amount > 0;
  const after = s.used + (counts ? amount : 0);
  const limit = s.credit_limit;
  const over = counts && limit > 0 && after > limit + 0.005;
  const branchOver = Boolean(counts && s.branch && s.branch.used + amount > s.branch.limit + 0.005);
  return {
    counts,
    exempt,
    after,
    availableAfter: limit > 0 ? limit - after : null,
    over,
    overBy: over ? after - limit : 0,
    branchOver,
  };
}

/** Share of the limit already used, 0..1 (for the bar). */
export function usedShare(used: number, limit: number): number {
  if (!(limit > 0)) return 0;
  return Math.min(Math.max(used / limit, 0), 1);
}

/** Loads the credit status whenever the picked customer changes. */
export function useCreditStatus(customer: Ref<string>, enabled: Ref<boolean> = ref(true)) {
  const status = ref<CreditStatus | null>(null);
  const loading = ref(false);
  let seq = 0;

  async function load() {
    const name = customer.value;
    const mine = ++seq;
    if (!name || !enabled.value) {
      status.value = null;
      return;
    }
    loading.value = true;
    try {
      const s = await creditStatus(name);
      if (mine === seq) status.value = s;
    } catch {
      if (mine === seq) status.value = null;
    } finally {
      if (mine === seq) loading.value = false;
    }
  }

  watch([customer, enabled], () => void load(), { immediate: true });
  return { status, loading, refresh: load };
}
