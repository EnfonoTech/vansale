<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listMine, fromCache, refreshCache, type CustomerRow } from "@/api/customer";
import { isOnline, useOnline } from "@/app/online";
import { NetworkError } from "@/app/frappe";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const online = useOnline();
const rows = ref<CustomerRow[]>([]);
const search = ref("");
const err = ref("");
const source = ref<"live" | "cache">("live");
const loading = ref(false);

async function load() {
  loading.value = true;
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
    if (e instanceof NetworkError) {
      err.value = "Offline — showing cached customers";
      rows.value = (await fromCache()).map((c) => c.raw as unknown as CustomerRow);
      source.value = "cache";
    } else {
      err.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    loading.value = false;
  }
}

onMounted(load);

let to: ReturnType<typeof setTimeout> | null = null;
watch(search, () => {
  if (to) clearTimeout(to);
  to = setTimeout(load, 250);
});

watch(online, (v) => { if (v) void load(); });

const filtered = computed(() => rows.value);

function openCustomer(c: CustomerRow) {
  void router.push({ name: "customer-detail", params: { name: c.name } });
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join("") || "?";
}
</script>

<template>
  <div class="stack">
    <div class="top-bar">
      <div class="search-bar">
        <Icon name="search" :size="18" class="search-ic" />
        <input v-model="search" placeholder="Search name, mobile, VAT" aria-label="Search customers" />
      </div>
      <button type="button" class="new-btn" @click="router.push({ name: 'customer-new' })">
        <Icon name="plus" :size="18" /> New
      </button>
    </div>

    <p v-if="source === 'cache'" class="muted small">
      <Icon name="wifi-off" :size="14" /> Offline — showing cached customers.
    </p>
    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && filtered.length === 0" class="stack">
      <div class="skeleton" style="height:3.5rem" />
      <div class="skeleton" style="height:3.5rem" />
      <div class="skeleton" style="height:3.5rem" />
    </div>
    <div v-else-if="filtered.length === 0" class="empty">
      <Icon name="customer" :size="32" class="empty-icon" />
      <strong>No customers found</strong>
      <span>{{ search ? "Try a different search." : "Ask your admin to add customers in this company." }}</span>
    </div>
    <ul v-else class="list">
      <li v-for="c in filtered" :key="c.name">
        <button class="item" type="button" @click="openCustomer(c)">
          <span class="avatar">{{ initials(c.customer_name) }}</span>
          <span class="body">
            <strong class="truncate">{{ c.customer_name }}</strong>
            <span class="muted small truncate">
              {{ c.mobile_no || c.territory || c.name }}
            </span>
          </span>
          <Icon name="chevron-right" :size="18" class="chev" />
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.top-bar { display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; align-items: center; }
.new-btn {
  all: unset; cursor: pointer;
  padding: 0 0.95rem; height: 2.5rem;
  background: var(--primary); color: var(--on-primary, white);
  border-radius: var(--radius);
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-weight: 600; font-size: var(--text-sm);
}
.search-bar {
  position: relative;
}
.search-ic {
  position: absolute; inset-inline-start: 0.7rem; top: 50%;
  transform: translateY(-50%); color: var(--text-faint); pointer-events: none;
}
.search-bar input { padding-inline-start: 2.3rem; }

.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.item {
  all: unset;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0.85rem;
  background: var(--surface);
  border-radius: var(--radius);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.item:active { transform: scale(0.99); background: var(--surface-muted); }
.avatar {
  width: 2.5rem; height: 2.5rem;
  border-radius: var(--radius-pill);
  display: grid; place-items: center;
  background: var(--primary-soft); color: var(--primary);
  font-weight: 700; font-size: var(--text-sm);
}
.body { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chev { color: var(--text-faint); }
</style>
