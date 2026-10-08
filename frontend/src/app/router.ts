/**
 * Router.
 *
 * Web: browser history under `/vansale/` (clean URLs). Frappe serves the
 * SPA's index.html for `/vansale` and every `/vansale/<path>` (www/vansale +
 * `website_route_rules` in hooks.py), so a refresh on a deep link loads the
 * app. Assets keep their `/assets/vansale/spa/` URLs.
 *
 * Native (APK): hash history — the WebView loads a bundled index.html and
 * has no server to answer `/vansale/<path>`.
 *
 * Old web links (`/assets/vansale/spa/index.html#/…`, from installs and
 * bookmarks before clean URLs) are forwarded to `/vansale/…`; a history
 * router with the `/vansale/` base would render nothing at that path.
 *
 * Guards:
 *   - Unauthenticated → /login
 *   - Authenticated but stale PIN → /pin (unlock mode)
 */
import { createRouter, createWebHashHistory, createWebHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";
import { useSessionStore } from "@/stores/session";
import { isNative, needsSiteSetup } from "./platform";

const WEB_BASE = import.meta.env.DEV ? "/" : "/vansale/";
const LEGACY_WEB_PATH = "/assets/vansale/spa/";

if (!isNative() && !import.meta.env.DEV && window.location.pathname.startsWith(LEGACY_WEB_PATH)) {
  const appPath = window.location.hash.replace(/^#\/?/, "");
  window.location.replace(WEB_BASE + appPath);
}

const routes: RouteRecordRaw[] = [
  { path: "/setup", name: "setup", component: () => import("@/views/SiteSetupView.vue") },
  { path: "/login", name: "login", component: () => import("@/views/LoginView.vue") },
  {
    path: "/pin",
    name: "pin",
    component: () => import("@/views/PinView.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/",
    name: "dashboard",
    component: () => import("@/views/DashboardView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/customers",
    name: "customers",
    component: () => import("@/views/CustomerListView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/customer/new",
    name: "customer-new",
    component: () => import("@/views/CustomerFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/customer/:name",
    name: "customer-detail",
    component: () => import("@/views/CustomerDetailView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
  {
    path: "/customer/:name/contact",
    name: "customer-contact",
    component: () => import("@/views/ContactFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/customer/:name/address/:address?",
    name: "customer-address",
    component: () => import("@/views/AddressFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/customer/:name/statement",
    name: "customer-statement",
    component: () => import("@/views/StatementView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
  {
    path: "/invoices",
    name: "invoices",
    component: () => import("@/views/InvoiceListView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/invoice/new",
    name: "invoice-new",
    component: () => import("@/views/InvoiceFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/invoice/:name",
    name: "invoice-detail",
    component: () => import("@/views/InvoiceDetailView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
  {
    path: "/invoice/:name/edit",
    name: "invoice-edit",
    component: () => import("@/views/InvoiceFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
  {
    path: "/invoice/:name/return",
    name: "invoice-return",
    component: () => import("@/views/SalesReturnView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
  {
    path: "/return/new",
    name: "return-new",
    component: () => import("@/views/ReturnFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/returns",
    name: "returns",
    component: () => import("@/views/ReturnsListView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/payments",
    name: "payments",
    component: () => import("@/views/PaymentListView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/payment/new",
    name: "payment-new",
    component: () => import("@/views/PaymentFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/payment/:name",
    name: "payment-detail",
    component: () => import("@/views/PaymentDetailView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
  {
    path: "/route",
    name: "route-today",
    component: () => import("@/views/RouteTodayView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/van-stock",
    name: "van-stock",
    component: () => import("@/views/VanStockView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/sync",
    name: "sync-errors",
    component: () => import("@/views/SyncErrorsView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    // `:store` is the IDB store name (e.g. "invoice_queue"), `:id` the
    // auto-incremented primary key. Coarse-grained on purpose — the
    // view itself handles the per-store payload shape so we don't have
    // to grow a route per queue type.
    path: "/sync/edit/:store/:id",
    name: "sync-edit-entry",
    component: () => import("@/views/EditQueueEntryView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
  {
    path: "/more",
    name: "more",
    component: () => import("@/views/MoreView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
  },
  {
    path: "/print/:doctype/:name",
    name: "print-view",
    component: () => import("@/views/PrintView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
    props: true,
  },
];

export const router = createRouter({
  history: isNative() ? createWebHashHistory(LEGACY_WEB_PATH) : createWebHistory(WEB_BASE),
  routes,
});

router.beforeEach((to) => {
  const session = useSessionStore();
  // Server first: without a site URL the APK cannot reach any endpoint, so
  // every other guard below would only produce network errors.
  if (needsSiteSetup() && to.name !== "setup") {
    return { name: "setup", replace: true };
  }
  // A server is configured, so never sit on the setup screen — send the user
  // wherever they actually belong. Gating this on `isAuthenticated` used to
  // leave a configured-but-signed-out app stranded on /setup.
  if (to.name === "setup" && !needsSiteSetup()) {
    return { name: session.isAuthenticated ? "dashboard" : "login", replace: true };
  }
  if (to.meta.requiresAuth && !session.isAuthenticated) {
    return { name: "login", replace: true };
  }
  if (to.meta.requiresPin && !session.pinStillValid) {
    return { name: "pin", replace: true };
  }
  if (to.name === "login" && session.isAuthenticated && session.pinStillValid) {
    return { name: "dashboard", replace: true };
  }
  // Route planning is per-van. When the van has it off, the screens stay
  // registered (deep links, back stack) but bounce to Home so a stale
  // history entry cannot resurrect a hidden module.
  if (to.name === "route-today" && session.defaults && !session.routeEnabled) {
    return { name: "dashboard", replace: true };
  }
  return true;
});
