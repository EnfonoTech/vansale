<script setup lang="ts">
/**
 * Saudi Riyal currency symbol.
 *
 * Renders the Unicode 17 Saudi Riyal sign (U+20C1) inside a span that
 * loads the custom "Saudi Riyal" font — so the glyph appears even on
 * operating systems that haven't shipped the symbol yet (Android 11+,
 * older iOS, most desktop browsers). The `.sar` class is defined in
 * `src/styles/saudi-riyal.css`.
 *
 * Drop-in replacement for "SAR" text when `session.currency === "SAR"`.
 * When the tenant currency is something else we fall back to the plain
 * ISO code so we don't invent a glyph for USD/AED/etc.
 *
 * Usage:
 *   <SarSymbol :code="session.currency" /> 1,234.56
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ code?: string | null }>(),
  { code: "SAR" },
);

const isSar = computed(() => (props.code ?? "").toUpperCase() === "SAR");
// U+20C1 is the officially assigned Unicode 17 Saudi Riyal sign.
const RIYAL_CHAR = "\u20C1";
</script>

<template>
  <span v-if="isSar" class="sar" aria-label="Saudi Riyal">{{ RIYAL_CHAR }}</span>
  <span v-else class="iso">{{ code }}</span>
</template>

<style scoped>
.iso {
  font-family: var(--font-mono, ui-monospace), monospace;
  font-size: 0.9em;
  letter-spacing: 0.02em;
  margin-inline-end: 0.25em;
}
</style>
