<script setup lang="ts">
/**
 * Lead detail — the entry point of the cycle: quote the lead, or convert it
 * to a customer (after which it is ordered and invoiced like any customer).
 */
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { leadDetail, convertLead, type LeadDetail } from "@/api/lead";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { useConfirmStore } from "@/stores/confirm";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const props = defineProps<{ name: string }>();
const router = useRouter();
const session = useSessionStore();
const toasts = useToastStore();
const confirm = useConfirmStore();

const lead = ref<LeadDetail | null>(null);
const err = ref("");
const busy = ref(false);

async function load() {
  err.value = "";
  try { lead.value = await leadDetail(props.name); }
  catch (e) { err.value = e instanceof Error ? e.message : String(e); }
}
onMounted(load);
watch(() => props.name, load);

const fmt = (n: number) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: session.currencyPrecision }).format(Number(n) || 0);

async function convert() {
  if (!lead.value || busy.value) return;
  const ok = await confirm.ask({
    title: "Convert to customer?",
    message: `${lead.value.company_name || lead.value.lead_name} becomes a customer you can order and invoice.`,
    confirmText: "Convert",
  });
  if (!ok) return;
  busy.value = true;
  try {
    const res = await convertLead(lead.value.name);
    toasts.success(`Customer ${res.customer} created`);
    void router.replace({ name: "customer-detail", params: { name: res.customer } });
  } catch (e) {
    toasts.error(e instanceof ApiError ? e.serverMessage ?? e.message : e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

// Notes are rich text on the desk; the app shows them as plain text.
const plain = (html: string) =>
  (html || "").replace(/<br\s*\/?>|<\/p>|<\/div>/gi, "\n").replace(/<[^>]+>/g, "").trim();

const converted = () => lead.value?.status === "Converted" || Boolean(lead.value?.customer);
</script>

<template>
  <div class="stack">
    <p v-if="err" class="error">{{ err }}</p>
    <div v-if="!lead && !err" class="skeleton" style="height:8rem" />

    <template v-if="lead">
      <section class="card stack">
        <div class="head">
          <div>
            <span class="muted xsmall">Lead · {{ lead.name }}</span>
            <h2 class="title">{{ lead.company_name || lead.lead_name }}</h2>
            <span v-if="lead.company_name && lead.lead_name" class="muted small">{{ lead.lead_name }}</span>
          </div>
          <span class="pill" :data-tone="converted() ? 'success' : 'info'">{{ lead.status }}</span>
        </div>
        <ul class="facts">
          <li v-if="lead.mobile_no"><Icon name="phone" :size="16" /><a :href="`tel:${lead.mobile_no}`">{{ lead.mobile_no }}</a></li>
          <li v-if="lead.email_id"><Icon name="user" :size="16" /><a :href="`mailto:${lead.email_id}`">{{ lead.email_id }}</a></li>
          <li v-if="lead.city || lead.territory"><Icon name="map-pin" :size="16" />{{ [lead.city, lead.territory].filter(Boolean).join(" · ") }}</li>
          <li v-if="lead.source"><Icon name="tag" :size="16" />{{ lead.source }}</li>
        </ul>
        <div class="actions">
          <template v-if="!converted()">
            <button class="primary" @click="router.push({ name: 'quotation-new', query: { lead: lead.name } })">
              <Icon name="receipt" :size="16" /> Quote
            </button>
            <button class="ghost" :disabled="busy" @click="convert"><Icon name="customer" :size="16" /> Convert</button>
            <button class="ghost" @click="router.push({ name: 'lead-edit', params: { name: lead.name } })">
              <Icon name="edit" :size="16" /> Edit
            </button>
          </template>
          <template v-else>
            <button class="primary" @click="router.push({ name: 'customer-detail', params: { name: lead.customer! } })">
              <Icon name="customer" :size="16" /> Open customer
            </button>
            <button class="ghost" @click="router.push({ name: 'quotation-new', query: { customer: lead.customer! } })">
              <Icon name="receipt" :size="16" /> Quote
            </button>
          </template>
        </div>
      </section>

      <section v-if="lead.quotations.length" class="card stack">
        <h3 class="section-h">Quotations</h3>
        <button v-for="q in lead.quotations" :key="q.name" class="row ghost"
                @click="router.push({ name: 'quotation-detail', params: { name: q.name } })">
          <span class="grow"><strong>{{ q.name }}</strong>
            <span class="muted xsmall"> · {{ q.transaction_date }}</span></span>
          <span class="tabular"><SarSymbol :code="session.currency" />{{ fmt(q.grand_total) }}</span>
          <span class="pill" data-tone="info">{{ q.status }}</span>
        </button>
      </section>

      <section v-if="lead.notes.length" class="card stack">
        <h3 class="section-h">Notes</h3>
        <ul class="notes">
          <li v-for="(n, i) in lead.notes" :key="i">
            <p style="white-space:pre-wrap; margin:0">{{ plain(n.note) }}</p>
            <span class="muted xsmall">{{ n.added_on }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.title { margin: 0.15rem 0 0.1rem; font-size: var(--text-lg); }
.facts { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.facts li { display: flex; align-items: center; gap: 0.5rem; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.actions button { flex: 1 1 7rem; min-height: 2.75rem; justify-content: center; }
.section-h { margin: 0 0 0.1rem; font-size: var(--text-sm); color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.row { display: flex; align-items: center; gap: 0.5rem; min-height: 2.75rem; text-align: start; }
.grow { flex: 1; min-width: 0; }
.tabular { font-variant-numeric: tabular-nums; }
.notes { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.6rem; }
</style>
