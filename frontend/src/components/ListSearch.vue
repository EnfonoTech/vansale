<script setup lang="ts">
/** Search box for the list screens (invoices, payments, returns). */
import Icon from "@/components/Icon.vue";

defineProps<{ placeholder?: string }>();
const model = defineModel<string>({ required: true });
</script>

<template>
  <div class="list-search">
    <Icon name="search" :size="16" class="ic" />
    <input v-model="model" type="search" :placeholder="placeholder ?? 'Search…'" enterkeyhint="search" />
    <button v-if="model" type="button" class="clear" aria-label="Clear search" @click="model = ''">
      <Icon name="x" :size="14" />
    </button>
  </div>
</template>

<style scoped>
.list-search { position: relative; }
.ic {
  position: absolute; top: 50%; inset-inline-start: 0.75rem;
  transform: translateY(-50%); color: var(--text-muted); pointer-events: none;
}
.list-search input { padding-inline: 2.2rem 2.4rem; }
.list-search input::-webkit-search-cancel-button { display: none; }
.clear {
  all: unset; box-sizing: border-box; cursor: pointer;
  position: absolute; top: 50%; inset-inline-end: 0.5rem; transform: translateY(-50%);
  width: 1.6rem; height: 1.6rem; border-radius: 999px;
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--text-muted); background: var(--surface-sunk);
}
</style>
