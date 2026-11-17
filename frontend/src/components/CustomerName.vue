<script setup lang="ts">
/**
 * A customer as list rows show it: the title (Badria: English name) in bold,
 * and the name the document stored (Badria: Arabic) under it when it differs.
 * Two root elements, so it fits the rows' column of lines.
 */
import { computed } from "vue";
import { otherCustomerName } from "@/app/customerName";

// unknown: some list rows are loosely typed records.
const props = defineProps<{ title?: unknown; name?: unknown; id?: unknown }>();
const text = (v: unknown) => (v == null ? "" : String(v));
const main = computed(() => (text(props.title) || text(props.name) || text(props.id)).trim());
const other = computed(() => otherCustomerName(text(props.title), text(props.name) || text(props.id)));
</script>

<template>
  <strong class="truncate">{{ main }}</strong>
  <span v-if="other" class="muted xsmall truncate cn-other" dir="auto">{{ other }}</span>
</template>

<style scoped>
/* Arabic reads right-to-left; keep the line under the title, not at the row's right edge. */
.cn-other { align-self: flex-start; max-width: 100%; }
</style>
