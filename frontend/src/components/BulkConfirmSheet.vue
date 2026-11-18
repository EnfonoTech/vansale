<script setup lang="ts">
// Placeholder so the screens can be built in parallel; replaced by the lists task.
import type { ApprovalItem } from "@/api/approvals";

defineProps<{ items: ApprovalItem[]; action: string; needsComment: boolean }>();
defineEmits<{ (e: "close"): void; (e: "done"): void }>();
</script>

<template>
  <div />
</template>
