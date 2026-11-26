<script setup lang="ts">
/**
 * Fix a queued entry the server refused (validation / not-found), so the
 * salesman does not lose a sale made on the route.
 *
 * A form, not a JSON editor: the lines (qty, rate, remove), how the sale is
 * paid, the cheque, the payment's amount and reference, the notes — what a
 * refusal usually asks to change. The raw JSON stays under "Advanced" for
 * support staff.
 *
 * On save the drain state is reset (attempts, error, backoff) so the next
 * cycle treats it as a fresh try. The `clientId` is kept, so server-side
 * idempotency still applies.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { db, type QueueStoreName } from "@/offline/db";
import { useSyncStore } from "@/stores/sync";
import { useSessionStore } from "@/stores/session";
import { modesOfPayment, type ModeOfPayment } from "@/api/payment";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const props = defineProps<{ store: string; id: string }>();

const router = useRouter();
const sync = useSyncStore();
const session = useSessionStore();

const store = computed<QueueStoreName>(() => props.store as QueueStoreName);
const entryId = computed<number>(() => Number(props.id));

type RawEntry = {
  id?: number;
  clientId: string;
  clientTs: string;
  createdAt: number;
  attempts: number;
  lastError?: string;
  errorKind?: string;
  nextAttemptAt?: number;
  status?: "pending" | "draining" | "dismissed";
  payload: Record<string, unknown>;
  [extra: string]: unknown;
};
interface Line {
  item_code: string;
  item_name?: string;
  qty: number;
  rate?: number;
  uom?: string;
  [extra: string]: unknown;
}
// The payload being edited: a copy of the queued one.
type Draft = Record<string, unknown> & { items?: Line[] };

const entry = ref<RawEntry | null>(null);
const draft = ref<Draft>({});
const loaded = ref(false);
const saveError = ref("");
const formError = ref("");
const saving = ref(false);
// Advanced: the raw payload, for support staff.
const jsonText = ref("");
const jsonDirty = ref(false);
const parseError = ref("");

const money = (n: number) => (Number(n) || 0).toFixed(session.currencyPrecision);
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

const kindTitle = computed(() => ({
  invoice_queue: "sale",
  payment_queue: "payment",
  stock_entry_queue: "stock load",
  visit_queue: "visit",
  return_queue: "return",
  customer_queue: "new customer",
}[store.value] ?? "entry"));
const isSale = computed(() => store.value === "invoice_queue");
const isPayment = computed(() => store.value === "payment_queue");
const lines = computed<Line[]>(() => (Array.isArray(draft.value.items) ? draft.value.items : []));
const hasRates = computed(() => lines.value.some((l) => l.rate != null));
const linesTotal = (items: Line[]) =>
  items.reduce((t, l) => t + (Number(l.qty) || 0) * (Number(l.rate) || 0), 0);
const origTotal = ref(0);
const origType = ref("");
const total = computed(() => linesTotal(lines.value));

const str = (k: string) => (draft.value[k] == null ? "" : String(draft.value[k]));
function setField(k: string, v: unknown) {
  if (v === "" || v == null) delete draft.value[k];
  else draft.value[k] = v;
}
const numModel = (k: string) =>
  computed<number | string>({
    get: () => (draft.value[k] == null ? "" : Number(draft.value[k])),
    set: (v) => setField(k, v === "" || v == null ? null : Number(v)),
  });
const textModel = (k: string) =>
  computed<string>({ get: () => str(k), set: (v) => setField(k, v.trim() ? v : null) });
const remarks = textModel("remarks");
const notes = textModel("notes");
const reason = textModel("reason");
const chequeNo = textModel("cheque_no");
const chequeDate = textModel("cheque_date");
const referenceNo = textModel("reference_no");
const referenceDate = textModel("reference_date");
const discount = numModel("discount_amount");
const loyalty = numModel("write_off_amount");
const paidAmount = numModel("paid_amount");

// Sale payment: Cash / Credit, and Cheque when the sale was a cheque.
const payType = computed(() => str("payment_type") || "credit");
const payTypes = computed(() => (origType.value === "cheque" ? ["cash", "credit", "cheque"] : ["cash", "credit"]));
const cashModes = ref<ModeOfPayment[]>([]);
const cashMode = computed<string>({
  get: () => str("mode_of_payment") || cashModes.value.find((m) => m.type === "Cash")?.name || "Cash",
  set: (v) => setField("mode_of_payment", v),
});
function setPayType(t: string) {
  const d = draft.value;
  if (t === payType.value) return;
  d.payment_type = t;
  // What belongs to the old way of paying goes; the new one starts whole.
  for (const k of ["payments", "cheque_amount", "cheque_rest_mode", "collect_later", "driver"]) delete d[k];
  if (t !== "cheque") { delete d.cheque_no; delete d.cheque_date; }
  if (t === "credit") { delete d.mode_of_payment; delete d.write_off_amount; }
  if (t === "cash") d.mode_of_payment = cashMode.value;
  if (t === "cheque") {
    const orig = entry.value?.payload ?? {};
    d.mode_of_payment = orig.mode_of_payment;
    d.cheque_no = orig.cheque_no;
    d.cheque_date = orig.cheque_date;
  }
}
// A split payment (several modes, or part cheque) was worked out for the old
// total; once the lines change it is paid whole in the main mode instead.
const hasSplit = computed(() => Boolean(draft.value.payments || draft.value.cheque_amount != null));
const splitReset = computed(() => hasSplit.value && Math.abs(total.value - origTotal.value) > 0.005);
const splitText = computed(() =>
  ((draft.value.payments as Array<{ mode_of_payment: string; amount?: number | null }> | undefined) ?? [])
    .map((p) => `${p.mode_of_payment} ${p.amount != null ? money(p.amount) : "(rest)"}`)
    .join(" + "),
);

function removeLine(i: number) {
  draft.value.items?.splice(i, 1);
}

async function load() {
  const d = await db();
  const row = (await (d.get as (s: QueueStoreName, k: number) => Promise<unknown>)(
    store.value,
    entryId.value,
  )) as RawEntry | undefined;
  loaded.value = true;
  if (!row) {
    entry.value = null;
    return;
  }
  entry.value = row;
  draft.value = clone(row.payload ?? {}) as Draft;
  origTotal.value = linesTotal(Array.isArray(draft.value.items) ? draft.value.items : []);
  origType.value = str("payment_type");
  if (isSale.value) {
    void modesOfPayment().then((m) => (cashModes.value = m.filter((x) => !x.pdc))).catch(() => {});
  }
}
onMounted(load);

function onAdvancedToggle(e: Event) {
  if ((e.target as HTMLDetailsElement).open && !jsonDirty.value) {
    jsonText.value = JSON.stringify(finalPayload(), null, 2);
  }
}

// The payload to queue: the form's, with a stale split dropped.
function finalPayload(): Record<string, unknown> {
  const out = clone(draft.value);
  if (splitReset.value) {
    delete out.payments;
    delete out.cheque_amount;
    delete out.cheque_rest_mode;
  }
  return out;
}

function check(p: Record<string, unknown>): string {
  const items = Array.isArray(p.items) ? (p.items as Line[]) : null;
  if (items) {
    if (!items.length) return "Keep at least one line";
    const bad = items.find((l) => !(Number(l.qty) > 0));
    if (bad) return `Enter a quantity for ${bad.item_name || bad.item_code}`;
    const neg = items.find((l) => l.rate != null && Number(l.rate) < 0);
    if (neg) return `The rate of ${neg.item_name || neg.item_code} can't be negative`;
  }
  if (isSale.value && p.payment_type === "cheque" && (!p.cheque_no || !p.cheque_date)) {
    return "Enter the cheque number and date";
  }
  if (isPayment.value && !(Number(p.paid_amount) > 0)) return "Enter the amount";
  return "";
}

async function save() {
  if (!entry.value) return;
  formError.value = "";
  parseError.value = "";
  saveError.value = "";
  let payload: Record<string, unknown>;
  if (jsonDirty.value) {
    try {
      const raw = JSON.parse(jsonText.value);
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        parseError.value = "Payload must be a JSON object";
        return;
      }
      payload = raw as Record<string, unknown>;
    } catch (err) {
      parseError.value = err instanceof Error ? err.message : String(err);
      return;
    }
  } else {
    payload = finalPayload();
  }
  formError.value = check(payload);
  if (formError.value) return;

  saving.value = true;
  try {
    const d = await db();
    const next: RawEntry = {
      ...entry.value,
      payload,
      // Reset drain state so the next cycle treats this as a new try.
      attempts: 0,
      lastError: undefined,
      errorKind: undefined,
      nextAttemptAt: undefined,
      status: "pending",
    };
    // Strip undefined keys — idb/IDB writes them as `undefined` which
    // keeps the bad state visible in the UI after save.
    for (const k of Object.keys(next) as Array<keyof RawEntry>) {
      if (next[k] === undefined) delete next[k];
    }
    await (d.put as (s: QueueStoreName, v: unknown) => Promise<IDBValidKey>)(store.value, next);
    await sync.refresh();
    // Kick a drain so the user sees the result immediately if online.
    void sync.requestDrain();
    await router.push({ name: "sync-errors" });
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : String(err);
  } finally {
    saving.value = false;
  }
}

function cancel() {
  void router.push({ name: "sync-errors" });
}
</script>

<template>
  <div class="stack">
    <header class="head">
      <h1>Fix queued {{ kindTitle }}</h1>
      <button class="ghost" @click="cancel">Cancel</button>
    </header>

    <div v-if="loaded && !entry" class="card muted small">
      Not found. It may have been sent already — go back to the sync queue.
    </div>

    <template v-else-if="entry">
      <p v-if="entry.lastError" class="refusal">
        <Icon name="alert" :size="16" />
        <span><strong>Not sent:</strong> {{ entry.lastError }}</span>
      </p>

      <!-- Who / what -->
      <section class="card stack-sm">
        <div v-if="draft.customer" class="kv">
          <span class="muted small">Customer</span>
          <strong>{{ draft.customer }}</strong>
        </div>
        <div v-if="draft.from_warehouse" class="kv">
          <span class="muted small">From</span>
          <strong>{{ draft.from_warehouse }}</strong>
        </div>
        <div v-if="isPayment && draft.mode_of_payment" class="kv">
          <span class="muted small">Mode</span>
          <strong>{{ draft.mode_of_payment }}</strong>
        </div>
        <div class="kv">
          <span class="muted small">Made</span>
          <span class="small">{{ new Date(entry.createdAt).toLocaleString() }}</span>
        </div>
      </section>

      <!-- Lines: qty, rate, remove -->
      <section v-if="lines.length || Array.isArray(draft.items)" class="card stack-sm">
        <div class="section-head">
          <h2>Lines</h2>
          <span v-if="hasRates" class="tabular small muted">
            <SarSymbol :code="session.currency" />{{ money(total) }} before tax
          </span>
        </div>
        <ul class="lines">
          <li v-for="(l, i) in lines" :key="i" class="line">
            <div class="line-head">
              <span class="line-name">
                <strong>{{ l.item_name || l.item_code }}</strong>
                <span v-if="l.item_name && l.item_name !== l.item_code" class="muted xsmall">{{ l.item_code }}</span>
              </span>
              <button v-if="lines.length > 1" type="button" class="icon-only small" aria-label="Remove line" @click="removeLine(i)">
                <Icon name="x" :size="14" />
              </button>
            </div>
            <div class="line-grid" :class="{ 'no-rate': l.rate == null }">
              <label class="field">
                <span class="tiny">Qty{{ l.uom ? ` (${l.uom})` : "" }}</span>
                <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.qty" />
              </label>
              <label v-if="l.rate != null" class="field">
                <span class="tiny">Rate</span>
                <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.rate" />
              </label>
              <div v-if="l.rate != null" class="line-amt tabular">
                <SarSymbol :code="session.currency" />{{ money((Number(l.qty) || 0) * (Number(l.rate) || 0)) }}
              </div>
            </div>
          </li>
        </ul>
        <p v-if="!lines.length" class="muted small">No lines left.</p>
      </section>

      <!-- Sale: how it is paid -->
      <section v-if="isSale && draft.payment_type" class="card stack-sm">
        <h2>Payment</h2>
        <div class="seg" :style="{ gridTemplateColumns: `repeat(${payTypes.length}, 1fr)` }">
          <button v-for="t in payTypes" :key="t" type="button" class="seg-btn" :data-active="payType === t" @click="setPayType(t)">
            {{ t === "cash" ? "Cash" : t === "credit" ? "Credit" : "Cheque" }}
          </button>
        </div>
        <label v-if="payType === 'cash' && (!draft.payments || splitReset) && !draft.collect_later" class="field">
          <span class="tiny">Mode of payment</span>
          <select v-model="cashMode">
            <option v-for="m in cashModes" :key="m.name" :value="m.name">{{ m.name }}</option>
            <option v-if="!cashModes.some((m) => m.name === cashMode)" :value="cashMode">{{ cashMode }}</option>
          </select>
        </label>
        <p v-if="payType === 'cash' && draft.collect_later" class="muted small">The delivery person collects the cash.</p>
        <div v-if="payType === 'cheque'" class="two">
          <label class="field">
            <span class="tiny">Cheque no. *</span>
            <input type="text" v-model="chequeNo" inputmode="numeric" />
          </label>
          <label class="field">
            <span class="tiny">Cheque date</span>
            <input type="date" v-model="chequeDate" />
          </label>
        </div>
        <div v-if="draft.payments && !splitReset" class="muted small">
          Paid in parts: {{ splitText }}
        </div>
        <p v-if="splitReset" class="note small">
          The lines changed, so the split payment is dropped: the whole sale is paid by
          {{ payType === "cheque" ? "the cheque" : cashMode }}.
        </p>
        <label v-if="draft.write_off_amount != null && payType !== 'credit'" class="field">
          <span class="tiny">Loyalty</span>
          <input type="number" min="0" step="any" inputmode="decimal" v-model="loyalty" />
        </label>
        <label v-if="draft.discount_amount != null" class="field">
          <span class="tiny">Invoice discount</span>
          <input type="number" min="0" step="any" inputmode="decimal" v-model="discount" />
        </label>
      </section>

      <!-- Payment: amount and reference -->
      <section v-if="isPayment" class="card stack-sm">
        <label class="field">
          <span class="tiny">Amount *</span>
          <input type="number" min="0" step="any" inputmode="decimal" v-model="paidAmount" />
        </label>
        <div class="two">
          <label class="field">
            <span class="tiny">Reference no.</span>
            <input type="text" v-model="referenceNo" />
          </label>
          <label class="field">
            <span class="tiny">Reference date</span>
            <input type="date" v-model="referenceDate" />
          </label>
        </div>
        <label v-if="draft.write_off_amount != null" class="field">
          <span class="tiny">Loyalty</span>
          <input type="number" min="0" step="any" inputmode="decimal" v-model="loyalty" />
        </label>
      </section>

      <!-- Notes -->
      <section class="card stack-sm">
        <label v-if="store === 'visit_queue'" class="field">
          <span class="tiny">Notes</span>
          <textarea v-model="notes" rows="2" />
        </label>
        <label v-else-if="store === 'stock_entry_queue'" class="field">
          <span class="tiny">Reason</span>
          <input type="text" v-model="reason" />
        </label>
        <label v-else class="field">
          <span class="tiny">Notes</span>
          <textarea v-model="remarks" rows="2" />
        </label>
      </section>

      <details class="advanced" @toggle="onAdvancedToggle">
        <summary class="small muted">Advanced: edit the raw data (support staff)</summary>
        <p class="muted xsmall">Changes here replace the form above when you save.</p>
        <textarea v-model="jsonText" rows="14" class="mono" spellcheck="false" @input="jsonDirty = true" />
        <p v-if="parseError" class="error small">Invalid JSON: {{ parseError }}</p>
      </details>

      <p v-if="formError" class="error small">{{ formError }}</p>
      <p v-if="saveError" class="error small">Save failed: {{ saveError }}</p>

      <div class="footer">
        <button class="ghost" :disabled="saving" @click="cancel">Cancel</button>
        <button :disabled="saving" @click="save">
          <Icon name="check" :size="16" /> {{ saving ? "Saving…" : "Save & send" }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 0.75rem; }
.stack-sm { display: flex; flex-direction: column; gap: 0.5rem; }
.head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.head h1 { margin: 0; font-size: var(--text-lg, 1.15rem); }
h2 { margin: 0; font-size: var(--text-base); }
.refusal {
  margin: 0; display: flex; gap: 0.5rem; align-items: flex-start;
  padding: 0.65rem 0.75rem; border-radius: var(--radius);
  background: var(--danger-soft); color: var(--danger); font-size: var(--text-sm); line-height: 1.4;
  overflow-wrap: anywhere;
}
.refusal :deep(svg) { flex: none; margin-top: 0.1rem; }
.kv { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; }
.kv strong { text-align: end; overflow-wrap: anywhere; }
.section-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; }
.lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.line { background: var(--surface-muted); border-radius: var(--radius); padding: 0.6rem 0.7rem; display: flex; flex-direction: column; gap: 0.35rem; }
.line-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.line-name { display: flex; flex-direction: column; min-width: 0; overflow-wrap: anywhere; }
.line-grid { display: grid; grid-template-columns: 1fr 1fr auto; gap: 0.5rem; align-items: end; }
.line-grid.no-rate { grid-template-columns: 1fr; }
.line-grid input { padding: 0.45rem 0.55rem; font-size: var(--text-sm); background: var(--surface); }
.line-amt { padding-bottom: 0.55rem; font-weight: 600; font-size: var(--text-sm); white-space: nowrap; }
.field { display: flex; flex-direction: column; gap: 0.2rem; }
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.seg { display: grid; gap: 0.5rem; }
.seg-btn {
  all: unset; cursor: pointer; padding: 0.55rem 0.75rem; border-radius: var(--radius-sm);
  background: var(--surface-muted); text-align: center; font-weight: 500;
}
.seg-btn[data-active="true"] { background: var(--primary); color: var(--on-primary, white); }
.note { margin: 0; padding: 0.45rem 0.6rem; border-radius: var(--radius-sm); background: var(--warning-soft); color: var(--warning); }
.advanced { padding: 0.25rem 0; }
.advanced summary { cursor: pointer; }
.advanced[open] { display: flex; flex-direction: column; gap: 0.4rem; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }
textarea.mono { width: 100%; resize: vertical; }
.footer { display: flex; justify-content: flex-end; gap: 0.5rem; }
.footer button { display: inline-flex; align-items: center; gap: 0.35rem; }
.tabular { font-variant-numeric: tabular-nums; }
.error { margin: 0; color: var(--danger); }
</style>
