<script setup lang="ts">
/**
 * Approvals: the shell around the four lists. To approve is the inbox the
 * user decides from; My requests, Sent back and History are for the person
 * who raised a document and for looking back.
 *
 * The inbox is kept fresh while this screen is open: it loads now, and the
 * store asks again every 60 s (and when the app comes back to the front or
 * the network returns). The poll stops when the screen is left.
 *
 * The tab is kept in the address (`?tab=`), so coming back from a document
 * lands on the same list. Pulling the page down at its top reloads it.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { useApprovalsStore } from "@/stores/approvals";
import { useSessionStore } from "@/stores/session";
import ApprovalHistory from "@/components/ApprovalHistory.vue";
import ApprovalMyRequests from "@/components/ApprovalMyRequests.vue";
import ApprovalSentBack from "@/components/ApprovalSentBack.vue";
import ApprovalToApprove from "@/components/ApprovalToApprove.vue";
import Icon from "@/components/Icon.vue";

type TabKey = "to-approve" | "mine" | "sent-back" | "history";

const TABS: { key: TabKey; label: string }[] = [
  { key: "to-approve", label: "approvalsInbox.tabs.toApprove" },
  { key: "mine", label: "approvalsInbox.tabs.myRequests" },
  { key: "sent-back", label: "approvalsInbox.tabs.sentBack" },
  { key: "history", label: "approvalsInbox.tabs.history" },
];

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const store = useApprovalsStore();
const session = useSessionStore();

const tab = computed<TabKey>(() => {
  const asked = String(route.query.tab ?? "");
  return TABS.some((entry) => entry.key === asked) ? (asked as TabKey) : "to-approve";
});

function setTab(key: TabKey) {
  if (key === tab.value) return;
  void router.replace({ name: "approvals", query: key === "to-approve" ? {} : { tab: key } });
}

/** The site has no approvals for this user (known once the settings are in). */
const unavailable = computed(() => session.defaults !== null && !session.approvalsEnabled);

onMounted(() => {
  if (unavailable.value) return;
  void store.refresh();
  store.startPolling();
});
onBeforeUnmount(() => store.stopPolling());

// --- pull to refresh ----------------------------------------------------------

const PULL_MAX = 88;
const PULL_TRIGGER = 64;
const pull = ref(0);
const reloadKey = ref(0);
let startX = 0;
let startY = 0;
let pulling = false;

function onTouchStart(event: TouchEvent) {
  if (window.scrollY > 0 || event.touches.length !== 1) return;
  startX = event.touches[0].clientX;
  startY = event.touches[0].clientY;
  pulling = true;
  pull.value = 0;
}

function onTouchMove(event: TouchEvent) {
  if (!pulling) return;
  const dy = event.touches[0].clientY - startY;
  const dx = event.touches[0].clientX - startX;
  // A sideways swipe (the area chips) or a scroll back up is not a pull.
  if (dy <= 0 || Math.abs(dx) > Math.abs(dy) || window.scrollY > 0) {
    pull.value = 0;
    return;
  }
  pull.value = Math.min(dy * 0.5, PULL_MAX);
}

function onTouchEnd() {
  const trigger = pulling && pull.value >= PULL_TRIGGER;
  pulling = false;
  pull.value = 0;
  if (trigger) void reload();
}

async function reload() {
  if (tab.value === "to-approve") await store.refresh();
  // The other lists load themselves when they appear: showing them again reloads them.
  else reloadKey.value++;
}
</script>

<template>
  <div
    class="approvals"
    @touchstart.passive="onTouchStart"
    @touchmove.passive="onTouchMove"
    @touchend.passive="onTouchEnd"
    @touchcancel.passive="onTouchEnd"
  >
    <div class="pull" :style="{ height: `${pull}px` }" aria-hidden="true">
      <template v-if="pull > 0">
        <Icon name="refresh" :size="16" />
        {{ pull >= PULL_TRIGGER ? t("approvalsInbox.pull.release") : t("approvalsInbox.pull.pull") }}
      </template>
    </div>

    <div v-if="unavailable" class="empty">
      <Icon name="approval" :size="32" class="empty-icon" />
      <strong>{{ t("approvalsInbox.unavailable") }}</strong>
    </div>

    <template v-else>
      <div class="tabs" role="tablist" :aria-label="t('approvalsInbox.tabs.label')">
        <button
          v-for="entry in TABS"
          :key="entry.key"
          type="button"
          role="tab"
          class="tab"
          :class="{ on: tab === entry.key }"
          :aria-selected="tab === entry.key"
          @click="setTab(entry.key)"
        >
          {{ t(entry.label) }}
          <span v-if="entry.key === 'to-approve' && store.badge > 0" class="count">{{ store.badge }}</span>
        </button>
      </div>

      <ApprovalToApprove v-if="tab === 'to-approve'" />
      <ApprovalMyRequests v-else-if="tab === 'mine'" :key="`mine-${reloadKey}`" />
      <ApprovalSentBack v-else-if="tab === 'sent-back'" :key="`sent-${reloadKey}`" />
      <ApprovalHistory v-else :key="`history-${reloadKey}`" />
    </template>
  </div>
</template>

<style scoped>
.approvals { display: flex; flex-direction: column; gap: 0.75rem; min-height: 60vh; }

.pull {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  overflow: hidden;
  margin-block-end: -0.75rem;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
}

/* Stays under the top bar while the list scrolls. */
.tabs {
  position: sticky;
  top: var(--top-bar-height);
  z-index: 5;
  display: flex;
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.tab {
  all: unset;
  box-sizing: border-box;
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
  padding: 0.7rem 0.15rem;
  min-height: 2.75rem;
  text-align: center;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-muted);
  border-bottom: 3px solid transparent;
  cursor: pointer;
}
.tab:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.tab.on { color: var(--text); border-bottom-color: var(--primary); }
.count {
  min-width: 1.15rem;
  padding: 0 0.35rem;
  border-radius: var(--radius-pill);
  background: var(--danger);
  color: #fff;
  font-size: var(--text-xs);
  line-height: 1.15rem;
}
</style>
