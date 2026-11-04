<script setup lang="ts">
/**
 * Quotation / Sales Order list. One view for both: `kind` picks the endpoint
 * and wording (see `KIND` in api/selling.ts).
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { KIND, listDocs, type SellingKind, type SellingRow } from "@/api/selling";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import ListSearch from "@/components/ListSearch.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const props = defineProps<{ kind: SellingKind }>();
const router = useRouter();
const session = useSessionStore();
const k = computed(() => KIND[props.kind]);

const rows = ref<SellingRow[]>([]);
const err = ref("");
const loading = ref(false);
const search = ref("");
let timer: number | undefined;
watch(search, () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(load, 300);
});
watch(() => props.kind, () => { rows.value = []; search.value = ""; void load(); });

async function load() {
  err.value = "";
  loading.value = rows.value.length === 0;
  try {
    rows.value = await listDocs(props.kind, 50, search.value.trim() || undefined);
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const fmt = (n: unknown) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: session.currencyPrecision }).format(Number(n) || 0);

function tone(r: SellingRow): string {
  const s = r.status.toLowerCase();
  if (s === "draft") return "info";
  if (["ordered", "completed", "to bill", "to deliver and bill"].includes(s)) return "success";
  if (["lost", "expired", "cancelled", "closed"].includes(s)) return "danger";
  return "warning";
}
const sub = (r: SellingRow) =>
  [r.name, r.transaction_date, props.kind === "quotation" && r.quotation_to === "Lead" ? "Lead" : ""]
    .filter(Boolean).join(" · ");
</script>

<template>
  <div class="stack">
    <div class="toolbar">
      <ListSearch v-model="search" :placeholder="`Search ${k.plural.toLowerCase()}`" />
      <button class="new-btn" :aria-label="`New ${k.title.toLowerCase()}`" @click="router.push({ name: k.new })">
        <Icon name="plus" :size="18" /> New
      </button>
    </div>

    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading" class="stack">
      <div class="skeleton" style="height:3.25rem" /><div class="skeleton" style="height:3.25rem" />
    </div>
    <div v-else-if="rows.length === 0 && search.trim()" class="empty">
      <Icon name="search" :size="32" class="empty-icon" />
      <strong>No matches</strong>
      <span class="muted">Nothing found for “{{ search.trim() }}”.</span>
    </div>
    <div v-else-if="rows.length === 0" class="empty">
      <Icon name="receipt" :size="32" class="empty-icon" />
      <strong>No {{ k.plural.toLowerCase() }} yet</strong>
      <button @click="router.push({ name: k.new })">New {{ k.title.toLowerCase() }}</button>
    </div>
    <ul v-else class="list">
      <li
        v-for="r in rows" :key="r.name" class="item" role="button" tabindex="0"
        @click="router.push({ name: k.detail, params: { name: r.name } })"
        @keyup.enter="router.push({ name: k.detail, params: { name: r.name } })"
      >
        <div class="body">
          <strong class="truncate">{{ r.customer_name || r.party_name }}</strong>
          <span class="muted xsmall">{{ sub(r) }}</span>
        </div>
        <div class="right">
          <strong><SarSymbol :code="session.currency" />{{ fmt(r.grand_total) }}</strong>
          <span class="pill" :data-tone="tone(r)">{{ r.status }}</span>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.5rem; align-items: center; }
.new-btn { height: 2.75rem; min-height: 0; padding: 0 0.95rem; white-space: nowrap; }
.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.item {
  background: var(--surface); border-radius: var(--radius); padding: 0.75rem 0.85rem;
  box-shadow: var(--shadow-sm); display: grid; grid-template-columns: 1fr auto; gap: 0.75rem;
  align-items: center; cursor: pointer;
  transition: transform var(--dur-fast) var(--ease);
}
.item:active { transform: scale(0.99); }
.item:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.body { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
.right { text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; }
.right strong { font-variant-numeric: tabular-nums; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
