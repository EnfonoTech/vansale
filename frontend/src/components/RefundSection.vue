<script setup lang="ts">
/**
 * Refund on a return, shared by both return screens.
 *
 * The server decides from the original invoice (preview `refundable`):
 * unpaid → the credit reduces that invoice's balance, nothing to pay back;
 * paid (or a bulk return) → the salesman may refund now — Payment Entry
 * "Pay", draft / submitted per the "Payment Entry status" setting.
 */
import { computed, onMounted, ref } from "vue";
import { modesOfPayment, type ModeOfPayment } from "@/api/payment";
import type { ReturnTotals } from "@/api/invoice";
import SarSymbol from "@/components/SarSymbol.vue";
import Icon from "@/components/Icon.vue";

export interface RefundState {
  on: boolean;
  mode: string;
  amount: number | null;
  reference: string;
}

const props = defineProps<{ totals: ReturnTotals | null; currency: string | null; precision: number }>();
const state = defineModel<RefundState>({ required: true });

const mops = ref<ModeOfPayment[]>([]);
const money = (n: number) => (Number(n) || 0).toFixed(props.precision);
const needsReference = (mode: string) => Boolean(mops.value.find((m) => m.name === mode)?.needs_reference);

// Like the sale's payment: the full credit by default (follows the total
// until edited); less = partial refund, the rest stays as customer credit.
const amountModel = computed<number | string>({
  get: () => (state.value.amount == null ? props.totals?.grand_total ?? 0 : state.value.amount),
  set: (v) => {
    const n = Number(v);
    state.value.amount = (v as unknown) === "" || !Number.isFinite(n) ? null : n;
  },
});
const remaining = computed(() =>
  state.value.amount == null || !props.totals ? 0 : Math.max(props.totals.grand_total - state.value.amount, 0),
);

onMounted(async () => {
  try {
    mops.value = await modesOfPayment();
  } catch {
    mops.value = [];
  }
  if (!state.value.mode && mops.value.length) {
    state.value.mode = (mops.value.find((m) => m.type === "Cash") ?? mops.value[0]).name;
  }
});
</script>

<template>
  <section v-if="totals && totals.grand_total > 0" class="card stack">
    <p v-if="!totals.refundable" class="muted small" style="margin:0">
      The invoice is unpaid — this credit reduces its balance
      <template v-if="totals.original_outstanding != null">
        (<SarSymbol :code="currency" />{{ money(totals.original_outstanding) }} outstanding)</template>.
      Nothing to pay back.
    </p>
    <template v-else>
      <span class="label">Refund</span>
      <!-- Same toggle as the sale's Cash / Credit. -->
      <div class="seg">
        <button type="button" class="seg-btn" :data-active="state.on" @click="state.on = true">
          <Icon name="payment" :size="16" /> Refund now
        </button>
        <button type="button" class="seg-btn" :data-active="!state.on" @click="state.on = false">
          <Icon name="clock" :size="16" /> Keep as credit
        </button>
      </div>
      <p v-if="!state.on" class="muted xsmall" style="margin:0">
        The credit stays on the customer's account.
      </p>
      <template v-else>
        <div class="refund-grid">
          <label class="field">
            <span class="tiny">Mode of Payment</span>
            <select v-model="state.mode">
              <option v-for="m in mops" :key="m.name" :value="m.name">{{ m.name }}</option>
            </select>
          </label>
          <label class="field">
            <span class="tiny">Amount</span>
            <input type="number" min="0" step="any" inputmode="decimal" v-model.number="amountModel" />
          </label>
          <input v-if="needsReference(state.mode)" class="full" type="text" v-model="state.reference"
                 placeholder="Reference no. (optional)" />
        </div>
        <div v-if="remaining > 0" class="rest muted small">
          <span>Stays as customer credit</span>
          <span><SarSymbol :code="currency" />{{ money(remaining) }}</span>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.seg-btn {
  all: unset; cursor: pointer;
  padding: 0.55rem 0.75rem; border-radius: var(--radius-sm);
  background: var(--surface-muted); text-align: center;
  font-weight: 500; display: inline-flex; justify-content: center; align-items: center; gap: 0.35rem;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.seg-btn[data-active="true"] { background: var(--primary); color: var(--on-primary, white); }
.refund-grid { display: grid; grid-template-columns: 1fr 8rem; gap: 0.5rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.rest { display: flex; justify-content: space-between; }
.refund-grid .full { grid-column: 1 / -1; }
</style>
