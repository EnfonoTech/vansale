<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listLeads, type LeadRow } from "@/api/lead";
import Icon from "@/components/Icon.vue";
import ListSearch from "@/components/ListSearch.vue";

const router = useRouter();
const rows = ref<LeadRow[]>([]);
const err = ref("");
const loading = ref(false);
const search = ref("");
let timer: number | undefined;
watch(search, () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(load, 300);
});

async function load() {
  err.value = "";
  loading.value = rows.value.length === 0;
  try {
    rows.value = await listLeads(50, search.value.trim() || undefined);
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function tone(status: string): string {
  if (status === "Converted") return "success";
  if (["Do Not Contact", "Lost Quotation"].includes(status)) return "danger";
  if (["Quotation", "Interested"].includes(status)) return "warning";
  return "info";
}
const title = (r: LeadRow) => r.company_name || r.lead_name;
const sub = (r: LeadRow) => [r.company_name ? r.lead_name : "", r.mobile_no, r.source].filter(Boolean).join(" · ");
</script>

<template>
  <div class="stack">
    <div class="toolbar">
      <ListSearch v-model="search" placeholder="Search leads" />
      <button class="new-btn" aria-label="New lead" @click="router.push({ name: 'lead-new' })">
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
      <Icon name="user" :size="32" class="empty-icon" />
      <strong>No leads yet</strong>
      <span class="muted">Capture a prospect you meet on the road.</span>
      <button @click="router.push({ name: 'lead-new' })">New lead</button>
    </div>
    <ul v-else class="list">
      <li v-for="r in rows" :key="r.name" class="item" role="button" tabindex="0"
          @click="router.push({ name: 'lead-detail', params: { name: r.name } })"
          @keyup.enter="router.push({ name: 'lead-detail', params: { name: r.name } })">
        <div class="body">
          <strong class="truncate">{{ title(r) }}</strong>
          <span class="muted xsmall truncate">{{ sub(r) || r.name }}</span>
        </div>
        <span class="pill" :data-tone="tone(r.status)">{{ r.status }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.5rem; align-items: center; }
.new-btn { height: 2.75rem; min-height: 0; padding: 0 0.95rem; white-space: nowrap; }
.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.item {
  background: var(--surface); border-radius: var(--radius); padding: 0.75rem 0.85rem; box-shadow: var(--shadow-sm);
  display: grid; grid-template-columns: 1fr auto; gap: 0.75rem; align-items: center; cursor: pointer;
  transition: transform var(--dur-fast) var(--ease);
}
.item:active { transform: scale(0.99); }
.item:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.body { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
