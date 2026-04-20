<script setup lang="ts">
/**
 * Single-source icon set. 24×24, stroke 1.75, currentColor.
 * Use by name: <Icon name="home" />. Add new icons in the switch block.
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ name: IconName; size?: number | string }>(),
  { size: 24 },
);

type IconName =
  | "home"
  | "route"
  | "invoice"
  | "payment"
  | "customer"
  | "stock"
  | "more"
  | "plus"
  | "search"
  | "back"
  | "check"
  | "x"
  | "refresh"
  | "wifi"
  | "wifi-off"
  | "truck"
  | "receipt"
  | "bag"
  | "user"
  | "map-pin"
  | "clock"
  | "chevron-right"
  | "sync"
  | "barcode"
  | "phone"
  | "edit"
  | "alert"
  | "logout"
  | "tag";

const sizePx = computed(() => (typeof props.size === "number" ? `${props.size}` : props.size));
</script>

<template>
  <svg
    :width="sizePx"
    :height="sizePx"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'home'">
      <path d="M3 12 12 3l9 9" />
      <path d="M5 10v10a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V10" />
    </template>
    <template v-else-if="name === 'route'">
      <circle cx="6" cy="5" r="2" />
      <circle cx="18" cy="19" r="2" />
      <path d="M8 5h7a3 3 0 0 1 3 3v1a3 3 0 0 1-3 3H9a3 3 0 0 0-3 3v1a3 3 0 0 0 3 3h7" />
    </template>
    <template v-else-if="name === 'invoice'">
      <path d="M6 2h10l4 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" />
      <path d="M16 2v4h4" />
      <path d="M8 11h8M8 15h8M8 19h5" />
    </template>
    <template v-else-if="name === 'payment'">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M2 10h20" />
      <path d="M6 15h4" />
    </template>
    <template v-else-if="name === 'customer'">
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c1-4 4-6 7-6s6 2 7 6" />
    </template>
    <template v-else-if="name === 'stock'">
      <path d="M3 7 12 3l9 4" />
      <path d="M3 7v10l9 4 9-4V7" />
      <path d="M12 11v10" />
      <path d="M3 7l9 4 9-4" />
    </template>
    <template v-else-if="name === 'more'">
      <circle cx="5" cy="12" r="1.5" fill="currentColor" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" />
      <circle cx="19" cy="12" r="1.5" fill="currentColor" />
    </template>
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>
    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </template>
    <template v-else-if="name === 'back'">
      <path d="M15 6l-6 6 6 6" />
    </template>
    <template v-else-if="name === 'check'">
      <path d="M5 12l4 4 10-10" />
    </template>
    <template v-else-if="name === 'x'">
      <path d="M6 6l12 12M18 6l-12 12" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M20 12a8 8 0 1 1-2.5-5.8L20 9" />
      <path d="M20 4v5h-5" />
    </template>
    <template v-else-if="name === 'wifi'">
      <path d="M2 9c6-5 14-5 20 0" />
      <path d="M5 13c4-3 10-3 14 0" />
      <path d="M9 17c1.5-1.3 4.5-1.3 6 0" />
      <circle cx="12" cy="20" r="0.9" fill="currentColor" />
    </template>
    <template v-else-if="name === 'wifi-off'">
      <path d="M2 9c2-1.7 4.3-2.9 6.8-3.7" />
      <path d="M15.5 5.5A13 13 0 0 1 22 9" />
      <path d="M5 13c1.5-1.2 3.3-2 5.2-2.5" />
      <path d="M14.3 10.7c1.8.5 3.4 1.3 4.7 2.3" />
      <path d="M9 17c1.5-1.3 4.5-1.3 6 0" />
      <circle cx="12" cy="20" r="0.9" fill="currentColor" />
      <path d="M3 3l18 18" />
    </template>
    <template v-else-if="name === 'truck'">
      <path d="M2 6h12v10H2z" />
      <path d="M14 10h4l3 3v3h-7" />
      <circle cx="6" cy="18" r="1.6" />
      <circle cx="17" cy="18" r="1.6" />
    </template>
    <template v-else-if="name === 'receipt'">
      <path d="M5 3h14v18l-2-2-2 2-2-2-2 2-2-2-2 2-2-2z" />
      <path d="M9 8h6M9 12h6M9 16h4" />
    </template>
    <template v-else-if="name === 'bag'">
      <path d="M5 8h14l-1 12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2z" />
      <path d="M8 8a4 4 0 0 1 8 0" />
    </template>
    <template v-else-if="name === 'user'">
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c1-4 4-6 7-6s6 2 7 6" />
    </template>
    <template v-else-if="name === 'map-pin'">
      <path d="M12 22s7-7.5 7-13a7 7 0 0 0-14 0c0 5.5 7 13 7 13z" />
      <circle cx="12" cy="9" r="2.5" />
    </template>
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </template>
    <template v-else-if="name === 'chevron-right'">
      <path d="M9 6l6 6-6 6" />
    </template>
    <template v-else-if="name === 'sync'">
      <path d="M4 12a8 8 0 0 1 14-5" />
      <path d="M20 6v4h-4" />
      <path d="M20 12a8 8 0 0 1-14 5" />
      <path d="M4 18v-4h4" />
    </template>
    <template v-else-if="name === 'barcode'">
      <path d="M4 5v14M7 5v14M10 5v14M13 5v14M16 5v14M19 5v14" />
    </template>
    <template v-else-if="name === 'phone'">
      <path d="M5 4h3l2 5-2 1a11 11 0 0 0 6 6l1-2 5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
    </template>
    <template v-else-if="name === 'edit'">
      <path d="M12 20h9" />
      <path d="M16 4l4 4-11 11H5v-4z" />
    </template>
    <template v-else-if="name === 'alert'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6M12 17v.01" />
    </template>
    <template v-else-if="name === 'logout'">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </template>
    <template v-else-if="name === 'tag'">
      <path d="M20 12l-8 8-9-9V3h8z" />
      <circle cx="7.5" cy="7.5" r="1.2" fill="currentColor" />
    </template>
  </svg>
</template>
