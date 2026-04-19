<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { listMine, fromCache, refreshCache, type CustomerRow } from "@/api/customer";
import { isOnline } from "@/app/online";
import { NetworkError } from "@/app/frappe";

const rows = ref<CustomerRow[]>([]);
const search = ref("");
const err = ref("");
const source = ref<"live" | "cache">("live");

async function load() {
  err.value = "";
  try {
    if (isOnline()) {
      rows.value = await listMine(search.value || undefined, 80);
      source.value = "live";
      if (!search.value) await refreshCache();
    } else {
      rows.value = (await fromCache()).map((c) => c.raw as unknown as CustomerRow);
      source.value = "cache";
    }
  } catch (e) {
    err.value = e instanceof NetworkError ? "Offline — showing cached customers" : (e instanceof Error ? e.message : String(e));
    if (e instanceof NetworkError) {
      rows.value = (await fromCache()).map((c) => c.raw as unknown as CustomerRow);
      source.value = "cache";
    }
  }
}

onMounted(load);

let to: ReturnType<typeof setTimeout> | null = null;
watch(search, () => {
  if (to) clearTimeout(to);
  to = setTimeout(load, 250);
});
</script>

<template>
  <section class="stack">
    <header class="card stack" style="gap: 0.5rem">
      <h1 style="margin: 0">Customers</h1>
      <input v-model="search" placeholder="Search by name / mobile / VAT" />
      <p v-if="source === 'cache'" class="muted small">Offline — showing cached data.</p>
      <p v-if="err" class="error">{{ err }}</p>
    </header>
    <ul class="list">
      <li v-for="c in rows" :key="c.name" class="item">
        <div>
          <strong>{{ c.customer_name }}</strong>
          <div class="muted small">{{ c.mobile_no || c.territory || c.name }}</div>
        </div>
      </li>
      <li v-if="rows.length === 0" class="muted">No customers found.</li>
    </ul>
  </section>
</template>

<style scoped>
.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.item {
  background: var(--surface);
  padding: 0.75rem;
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}
.small { font-size: 0.82rem; }
</style>
