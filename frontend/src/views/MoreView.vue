<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { approvalsOnly } from "@/features/approvals/inbox";
import { useSessionStore } from "@/stores/session";
import { useApprovalsStore } from "@/stores/approvals";
import { usePushStore } from "@/stores/push";
import { canToggle, isOn, statusKey } from "@/features/push/toggle";
import { isIos } from "@/features/push/support";
import { logout } from "@/api/auth";
import { forgetPin } from "@/app/pin-offline";
import { useSyncStore } from "@/stores/sync";
import { useConfirmStore } from "@/stores/confirm";
import { clearSiteUrl, isNative, siteUrl } from "@/app/platform";
import { useOnline } from "@/app/online";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();
const approvals = useApprovalsStore();
const push = usePushStore();
const online = useOnline();
const { t } = useI18n();
const sync = useSyncStore();
const confirm = useConfirmStore();
const appVersion = __APP_VERSION__;

const showSiteRow = isNative();
const currentSite = computed(() => (siteUrl() ?? "").replace(/^https?:\/\//, ""));

function onChangePin() {
  // Reuses PinView's keypad in `change` mode — see that view's Mode comment.
  void router.push({ name: "pin", query: { change: "1" } });
}

/**
 * Repoint the APK at a different Frappe site.
 *
 * Guarded on an empty sync queue: queued invoices, payments and stock
 * entries belong to the site they were created against. Draining them into
 * a different company's ledger would post real documents in the wrong
 * books, and there is no clean way to translate customer / item / warehouse
 * names across sites. Credentials are per-site too, so this always logs out.
 */
async function onChangeSite() {
  if (sync.pending > 0) {
    await confirm.ask({
      title: "Sync first",
      message:
        `${sync.pending} item${sync.pending === 1 ? "" : "s"} still waiting to reach the server. ` +
        `Get back online and let them sync before switching servers — they cannot be moved to another site.`,
      confirmText: "OK",
      cancelText: "Close",
    });
    return;
  }
  const ok = await confirm.ask({
    title: "Change server?",
    message: "You will be signed out and asked for the server address again.",
    confirmText: "Change server",
    danger: true,
  });
  if (!ok) return;
  try {
    await logout();
  } finally {
    approvals.reset();
    session.logout();
    await clearSiteUrl();
    await router.replace({ name: "setup" });
  }
}

// Approval notifications (Web Push): the web app only, for someone who approves, on a server that can send.
const pushWanted = computed(() => session.approvalsEnabled && !isNative());
const showPush = computed(() => pushWanted.value && push.visible);
const pushOn = computed(() => isOn(push.toggle));
const pushLocked = computed(() => !canToggle(push.toggle, online.value));
const pushIos =
  typeof navigator !== "undefined" && isIos(navigator.userAgent, navigator.platform, navigator.maxTouchPoints);
const pushStatus = computed(() => t(`approvalsPush.status.${statusKey(push.toggle, online.value, pushIos)}`));

function refreshPush() {
  if (pushWanted.value) void push.refresh();
}
function onVisible() {
  // Back from the browser's settings: the permission may have changed there.
  if (document.visibilityState === "visible") refreshPush();
}
onMounted(() => {
  refreshPush();
  document.addEventListener("visibilitychange", onVisible);
});
onBeforeUnmount(() => document.removeEventListener("visibilitychange", onVisible));
watch(pushWanted, refreshPush);
watch(online, (now) => {
  if (now) refreshPush();
});

function onPushToggle(event: Event) {
  const input = event.target as HTMLInputElement;
  // Straight from the tap: the permission prompt needs it, so nothing is awaited first.
  if (input.checked) void push.enable();
  else void push.disable();
  // The switch follows the store, never the tap: a refused or ignored tap springs back.
  input.checked = pushOn.value;
}

const initials = computed(() => {
  const name = session.fullName ?? session.email ?? "";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s.charAt(0).toUpperCase())
    .join("") || "?";
});

async function onLogout() {
  // Same guard as changing server: queued sales would otherwise drain under
  // the next user's login and post as that user.
  if (sync.pending > 0) {
    await confirm.ask({
      title: "Sync first",
      message:
        `${sync.pending} item${sync.pending === 1 ? "" : "s"} still waiting to reach the server. ` +
        `Get back online and let them sync before logging out.`,
      confirmText: "OK",
      cancelText: "Close",
    });
    return;
  }
  forgetPin();
  // Stop this device receiving the user's approvals. Before the server logout, which ends the session
  // the call needs; quick, and it never throws, so it cannot hold the logout up.
  await push.detach();
  try { await logout(); }
  finally { approvals.reset(); push.reset(); session.logout(); await router.replace({ name: "login" }); }
}

interface Link {
  icon: "customer" | "user" | "bag" | "stock" | "sync" | "refresh" | "truck" | "invoice" | "receipt" | "plus" | "payment" | "approval";
  label: string;
  sub?: string;
  to: string;
  tone?: "primary" | "success" | "warning" | "danger";
  badge?: number | null;
}

/** The Approvals shortcut, with how many wait; none on a site without approvals. */
const approvalsRow = computed<Link | null>(() =>
  session.approvalsEnabled
    ? {
        icon: "approval",
        label: t("approvalsInbox.more.label"),
        sub: t("approvalsInbox.more.sub"),
        to: "approvals",
        tone: "warning",
        badge: approvals.badge > 0 ? approvals.badge : null,
      }
    : null,
);

const links = computed<Link[]>(() => {
  // No van setup: only what such a user can use. The van shortcuts open
  // screens that read van endpoints.
  if (approvalsOnly(session)) return approvalsRow.value ? [approvalsRow.value] : [];
  const rows: Link[] = [
    { icon: "plus", label: "New invoice", sub: "Start a sale", to: "invoice-new", tone: "primary" },
    { icon: "user", label: "Leads", sub: "Prospects to follow up", to: "leads" },
    { icon: "receipt", label: "Quotations", sub: "Offers sent to customers", to: "quotations" },
    { icon: "bag", label: "Sales orders", sub: "Confirmed orders to invoice", to: "orders" },
    { icon: "invoice", label: "All invoices", sub: "Browse submitted & drafts", to: "invoices" },
    { icon: "payment", label: "Payments", sub: "Collections & receipts", to: "payments", tone: "success" },
    { icon: "receipt", label: "Returns", sub: "Credit notes against invoices", to: "returns", tone: "warning" },
    { icon: "customer", label: "Customers", sub: "Browse & create", to: "customers" },
  ];
  // Right after "New invoice": the second thing a van user who also approves reaches for.
  if (approvalsRow.value) rows.splice(1, 0, approvalsRow.value);
  // When route planning is off, Van Stock owns the fourth nav tab, so
  // repeating it here would be dead weight. When it is on, Van Stock has no
  // tab of its own and this is its only entry point.
  if (session.routeEnabled) {
    rows.push({ icon: "stock", label: "Van stock", sub: "Current warehouse", to: "van-stock", tone: "success" });
    rows.push({ icon: "truck", label: "Today's route", sub: "Stops, visits, signatures", to: "route-today" });
  }
  rows.push({
    icon: "sync",
    label: "Sync errors",
    sub: sync.pending > 0 ? `${sync.pending} pending` : sync.lastError ?? "All clear",
    to: "sync-errors",
    tone: sync.pending > 0 || sync.lastError ? "danger" : undefined,
    badge: sync.pending > 0 ? sync.pending : null,
  });
  return rows;
});
</script>

<template>
  <div class="stack more">
    <section class="profile card">
      <div class="avatar">{{ initials }}</div>
      <div class="identity">
        <strong class="truncate">{{ session.fullName || session.email }}</strong>
        <span class="muted xsmall truncate">{{ session.email }}</span>
        <div v-if="session.defaults && !approvalsOnly(session)" class="van-chip">
          <Icon name="truck" :size="14" />
          <span>{{ session.defaults.van_code ?? "—" }}</span>
          <span v-if="session.defaults.default_warehouse" class="dot">·</span>
          <span v-if="session.defaults.default_warehouse">{{ session.defaults.default_warehouse }}</span>
        </div>
      </div>
    </section>

    <section v-if="links.length" class="card stack">
      <h3 class="section-h">Shortcuts</h3>
      <ul class="link-list">
        <li
          v-for="l in links"
          :key="l.to"
          class="link-row"
          role="button"
          tabindex="0"
          @click="router.push({ name: l.to })"
          @keyup.enter="router.push({ name: l.to })"
        >
          <Icon :name="l.icon" :size="18" class="link-icon" :data-tone="l.tone" />
          <div class="link-body">
            <strong>{{ l.label }}</strong>
            <span v-if="l.sub" class="muted xsmall">{{ l.sub }}</span>
          </div>
          <span v-if="l.badge" class="pill" data-tone="danger">{{ l.badge }}</span>
          <Icon name="chevron-right" :size="16" class="chev" />
        </li>
      </ul>
    </section>

    <section class="card stack">
      <h3 class="section-h">App</h3>
      <div class="meta-row">
        <span class="muted">Version</span>
        <span>{{ appVersion }}</span>
      </div>
      <div class="meta-row">
        <span class="muted">Language</span>
        <span>{{ session.language ?? "en" }}</span>
      </div>
      <div class="meta-row">
        <span class="muted">Currency</span>
        <span><SarSymbol :code="session.currency" /> {{ session.currency }}</span>
      </div>
      <label
        v-if="showPush"
        class="switch-row"
        :data-locked="pushLocked || undefined"
        :aria-busy="push.toggle.kind === 'busy' || undefined"
      >
        <span class="switch-text">
          <strong>{{ t("approvalsPush.label") }}</strong>
          <span
            class="muted xsmall"
            :data-tone="push.toggle.kind === 'error' ? 'danger' : undefined"
            role="status"
            aria-live="polite"
          >{{ pushStatus }}</span>
        </span>
        <input
          type="checkbox"
          role="switch"
          class="switch"
          :checked="pushOn"
          :disabled="pushLocked"
          @change="onPushToggle"
        />
      </label>
      <button v-if="session.pinRequired" class="ghost small site-btn" @click="onChangePin">
        Change PIN
      </button>
      <template v-if="showSiteRow">
        <div class="meta-row">
          <span class="muted">Server</span>
          <span class="truncate">{{ currentSite || "—" }}</span>
        </div>
        <button class="ghost small site-btn" @click="onChangeSite">Change server</button>
      </template>
    </section>

    <button class="danger-ghost" @click="onLogout">
      <Icon name="logout" :size="18" /> Log out
    </button>
  </div>
</template>

<style scoped>
.more { gap: 0.875rem; padding-bottom: 1.5rem; }

.site-btn { align-self: flex-start; }

.profile {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.85rem;
  align-items: center;
  padding: 1rem;
}
.avatar {
  width: 3.25rem; height: 3.25rem;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, var(--primary) 0%, color-mix(in srgb, var(--primary) 70%, #0f172a) 100%);
  color: var(--primary-ink);
  display: grid; place-items: center;
  font-weight: 700;
  font-size: var(--text-lg);
  box-shadow: var(--shadow-sm);
}
.identity { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.van-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.25rem;
  padding: 0.2rem 0.55rem;
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 600;
  align-self: flex-start;
}
.van-chip .dot { color: var(--text-faint); }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.section-h {
  margin: 0 0 0.1rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.link-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.2rem; }
.link-row {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  gap: 0.65rem;
  align-items: center;
  padding: 0.65rem 0.5rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}
.link-row:hover, .link-row:focus-visible { background: var(--surface-muted); outline: none; }
.link-icon {
  padding: 0.45rem;
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: var(--radius-sm);
  box-sizing: content-box;
}
.link-icon[data-tone="success"] { background: var(--success-soft); color: var(--success); }
.link-icon[data-tone="warning"] { background: var(--warning-soft); color: var(--warning); }
.link-icon[data-tone="danger"] { background: var(--danger-soft); color: var(--danger); }
.link-body { display: flex; flex-direction: column; gap: 0.05rem; min-width: 0; }
.chev { color: var(--text-muted); }

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  min-height: 2.75rem;
  cursor: pointer;
}
.switch-row[data-locked] { cursor: default; }
.switch-text { display: flex; flex-direction: column; gap: 0.05rem; min-width: 0; }
.switch-text [data-tone="danger"] { color: var(--danger); }
.switch {
  appearance: none;
  -webkit-appearance: none;
  flex-shrink: 0;
  position: relative;
  width: 2.6rem;
  height: 1.5rem;
  padding: 0;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--border-strong);
  cursor: inherit;
  transition: background var(--dur-fast) var(--ease);
}
.switch::after {
  content: "";
  position: absolute;
  inset-block-start: 0.18rem;
  inset-inline-start: 0.18rem;
  width: 1.14rem;
  height: 1.14rem;
  border-radius: 50%;
  background: #fff;
  box-shadow: var(--shadow-sm);
  transition: inset-inline-start var(--dur-fast) var(--ease);
}
.switch:checked { background: var(--primary); }
.switch:checked::after { inset-inline-start: 1.28rem; }
.switch:disabled { opacity: 0.55; }
.switch:focus-visible { box-shadow: 0 0 0 3px var(--primary-soft-strong); outline: none; }

.meta-row { display: flex; justify-content: space-between; align-items: baseline; font-variant-numeric: tabular-nums; }

.danger-ghost {
  all: unset;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  min-height: 3rem;
  border-radius: var(--radius);
  background: var(--danger-soft);
  color: var(--danger);
  font-weight: 600;
  transition: transform var(--dur-fast) var(--ease);
}
.danger-ghost:active { transform: scale(0.98); }
</style>
