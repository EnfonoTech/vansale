<script setup lang="ts">
/**
 * Under a line of an invoice / quotation / order: the last price this
 * customer paid for the item and a warning when stock is short; on tap, the
 * item's recent sales and its stock in every warehouse.
 */
import { computed, ref } from "vue";
import { itemInsight, type ItemInsight, type PastSale } from "@/api/item";
import { isOnline } from "@/app/online";
import { stockLabel } from "@/features/van/stock";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const props = defineProps<{
  itemCode: string;
  customer?: string;
  /** The line's unit and its conversion factor. */
  uom?: string;
  conversionFactor?: number;
  last: PastSale | null;
  /** Available in the line's unit when the lines need more; else null. */
  short: number | null;
}>();

const emit = defineEmits<{ (e: "use", rate: number): void }>();
const session = useSessionStore();

/** A past sale's rate in the line's unit (it may have been sold in another). */
function inLineUnit(s: PastSale): number {
  const lineCf = Number(props.conversionFactor) || 1;
  const soldCf = Number(s.conversion_factor) || 1;
  return s.uom === props.uom ? s.rate : (s.rate / soldCf) * lineCf;
}
const use = (s: PastSale) => emit("use", inLineUnit(s));
const open = ref(false);
const loading = ref(false);
const failed = ref("");
const data = ref<ItemInsight | null>(null);
let loadedFor = "";

const rate = (n: number) =>
  new Intl.NumberFormat(undefined, {
    minimumFractionDigits: session.ratePrecision,
    maximumFractionDigits: session.ratePrecision,
  }).format(Number(n) || 0);
const qty = (n: number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(n) || 0);
const day = (d: string) => {
  const t = new Date(`${d}T00:00:00`);
  return Number.isNaN(t.getTime()) ? d : t.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "2-digit" });
};

async function toggle() {
  open.value = !open.value;
  const key = `${props.itemCode}|${props.customer ?? ""}`;
  if (!open.value || loadedFor === key) return;
  if (!isOnline()) {
    failed.value = "Needs a connection.";
    return;
  }
  loading.value = true;
  failed.value = "";
  try {
    data.value = await itemInsight(props.itemCode, props.customer || undefined);
    loadedFor = key;
  } catch {
    failed.value = "Couldn't load the history.";
  } finally {
    loading.value = false;
  }
}

const stockText = (n: number) =>
  stockLabel(n, data.value?.stock_uom, data.value?.sales_uom, data.value?.sales_cf);
const nothing = computed(
  () => data.value && !data.value.to_customer.length && !data.value.recent.length && !data.value.warehouses.length,
);
</script>

<template>
  <div class="insight">
    <div class="ins-row">
      <button v-if="last" type="button" class="use-last xsmall" title="Use this price" @click="use(last)">
        Last to this customer: <SarSymbol :code="session.currency" /><strong>{{ rate(last.rate) }}</strong><template v-if="last.uom"> / {{ last.uom }}</template>
        · {{ day(last.posting_date) }}
        <span class="use-chip">Use</span>
      </button>
      <span v-if="short !== null" class="xsmall short">
        <Icon name="alert" :size="12" /> Only {{ qty(short) }}{{ uom ? ` ${uom}` : "" }} in stock
      </span>
      <button type="button" class="ins-toggle xsmall" :aria-expanded="open" @click="toggle">
        {{ open ? "Hide" : "History & stock" }}
      </button>
    </div>

    <div v-if="open" class="ins-panel">
      <p v-if="loading" class="xsmall muted">Loading…</p>
      <p v-else-if="failed" class="xsmall muted">{{ failed }}</p>
      <template v-else-if="data">
        <div v-if="data.to_customer.length" class="ins-block">
          <span class="tiny">This customer</span>
          <button v-for="s in data.to_customer" :key="s.invoice + s.posting_date + s.rate" type="button"
                  class="ins-line pick" @click="use(s)">
            <span>{{ day(s.posting_date) }}</span>
            <span class="muted">{{ qty(s.qty) }} {{ s.uom }}</span>
            <strong class="tabular"><SarSymbol :code="session.currency" />{{ rate(s.rate) }}</strong>
          </button>
        </div>
        <div v-if="data.recent.length" class="ins-block">
          <span class="tiny">{{ customer ? "Other customers" : "Recent sales" }} · last 12 months</span>
          <button v-for="s in data.recent" :key="s.invoice + s.customer + s.rate" type="button"
                  class="ins-line pick" @click="use(s)">
            <span>{{ day(s.posting_date) }}</span>
            <span class="muted truncate">{{ s.customer_name }} · {{ qty(s.qty) }} {{ s.uom }}</span>
            <strong class="tabular"><SarSymbol :code="session.currency" />{{ rate(s.rate) }}</strong>
          </button>
        </div>
        <div v-if="data.warehouses.length" class="ins-block">
          <span class="tiny">Stock</span>
          <div v-for="w in data.warehouses" :key="w.warehouse" class="ins-line">
            <span class="truncate" :class="{ own: w.own }">{{ w.warehouse_name }}<template v-if="w.own"> (yours)</template></span>
            <span />
            <strong class="tabular" :class="{ zero: w.qty <= 0 }">{{ stockText(w.qty) }}</strong>
          </div>
        </div>
        <p v-if="data.to_customer.length || data.recent.length" class="xsmall muted">
          Tap a price to use it.
          {{ data.sales_scope ? `Sales of ${data.sales_scope} only.` : "Sales of the whole company." }}
        </p>
        <p v-if="nothing" class="xsmall muted">No sales or stock found for this item.</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.insight { display: flex; flex-direction: column; gap: 0.3rem; }
.ins-row { display: flex; flex-wrap: wrap; align-items: center; gap: 0.25rem 0.6rem; }
.short { color: var(--danger); font-weight: 600; display: inline-flex; align-items: center; gap: 0.2rem; }
.ins-toggle {
  all: unset; cursor: pointer; margin-inline-start: auto;
  color: var(--primary); font-weight: 600; padding: 0.15rem 0;
}
.ins-panel {
  display: flex; flex-direction: column; gap: 0.5rem;
  padding: 0.5rem 0.6rem; border-radius: var(--radius-sm); background: var(--surface-muted);
}
.ins-block { display: flex; flex-direction: column; gap: 0.15rem; }
.use-last { all: unset; cursor: pointer; color: var(--text-muted); font-size: var(--text-xs); display: inline-flex; flex-wrap: wrap; align-items: center; gap: 0.2rem; }
.use-chip {
  margin-inline-start: 0.2rem; padding: 0 0.45rem; border-radius: 999px;
  background: var(--primary-soft); color: var(--primary); font-weight: 600;
}
.pick { all: unset; cursor: pointer; border-radius: 4px; display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 0.5rem; align-items: baseline; font-size: var(--text-xs); }
.pick:active { background: var(--primary-soft); }
.ins-line {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 0.5rem; align-items: baseline;
  font-size: var(--text-xs);
}
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.tabular { font-variant-numeric: tabular-nums; white-space: nowrap; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.own { font-weight: 600; }
.zero { color: var(--text-faint); }
</style>
