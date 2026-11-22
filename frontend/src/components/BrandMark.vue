<script setup lang="ts">
/**
 * Customer brand mark for the auth screens.
 *
 * `scripts/generate-customer-assets.mjs brand` stages the customer's logo
 * as `public/brand-logo.png` before the vite build. When no logo was
 * supplied that file is absent, so the <img> 404s — we swap to the built-in
 * truck icon on error rather than shipping a broken-image glyph.
 *
 * The URL is resolved against `import.meta.env.BASE_URL` because the two
 * build targets use different bases (`/assets/vansale/spa/` for the
 * Frappe-served PWA, `./` for the Capacitor WebView).
 */
import { computed, ref, watch } from "vue";
import { useBranding } from "@/app/branding";
import Icon from "./Icon.vue";

const props = withDefaults(defineProps<{ size?: number }>(), { size: 28 });

const { branding } = useBranding();
const buildLogoUrl = `${import.meta.env.BASE_URL}brand-logo.png`;

// The Login logo from Vansale Settings first, then the logo staged at build time,
// then the built-in truck: a file that fails to load steps down to the next.
const configuredFailed = ref(false);
const buildFailed = ref(false);
watch(() => branding.value.logoUrl, () => { configuredFailed.value = false; });

const logoUrl = computed(() => {
  if (branding.value.logoUrl && !configuredFailed.value) return branding.value.logoUrl;
  return buildFailed.value ? "" : buildLogoUrl;
});

function onLogoError() {
  if (branding.value.logoUrl && !configuredFailed.value) configuredFailed.value = true;
  else buildFailed.value = true;
}
</script>

<template>
  <Icon v-if="!logoUrl" name="truck" :size="props.size" />
  <img
    v-else
    :src="logoUrl"
    alt=""
    class="brand-logo"
    @error="onLogoError"
  />
</template>

<style scoped>
/* Fill the parent tile: customer icons ship with their own background and
   rounded frame, so insetting them inside another tinted tile reads as a
   mistake. `inherit` picks up the tile's radius; parents set overflow. */
.brand-logo {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: inherit;
  display: block;
}
</style>
