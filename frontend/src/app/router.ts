/**
 * Router — hash history everywhere, base = full asset path.
 *
 * The web PWA is served via Frappe's `website_redirects` which 301s
 * `/vansale` → `/assets/vansale/spa/index.html`. Using `createWebHistory`
 * with base `"/vansale/"` fails because the post-redirect URL doesn't
 * start with that base (it starts with `/assets/vansale/spa/`), leaving
 * RouterView unable to resolve any route — empty screen. Also, any deep
 * refresh (`/vansale/login`) hits the server which has no rule for that
 * subpath → Frappe 404.
 *
 * Hash history with the asset-path base fixes both: the hash fragment
 * drives routing entirely client-side, and the browser only ever requests
 * the real static `index.html` on refresh. This mirrors fatehhr's proven
 * setup.
 *
 * Guards:
 *   - Unauthenticated → /login
 *   - Authenticated but stale PIN → /pin (unlock mode)
 */
import { createRouter, createWebHashHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";
import { useSessionStore } from "@/stores/session";

const routes: RouteRecordRaw[] = [
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
    path: "/returns",
    name: "returns",
    component: () => import("@/views/ReturnsListView.vue"),
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
  history: createWebHashHistory("/assets/vansale/spa/"),
  routes,
});

router.beforeEach((to) => {
  const session = useSessionStore();
  if (to.meta.requiresAuth && !session.isAuthenticated) {
    return { name: "login", replace: true };
  }
  if (to.meta.requiresPin && !session.pinStillValid) {
    return { name: "pin", replace: true };
  }
  if (to.name === "login" && session.isAuthenticated && session.pinStillValid) {
    return { name: "dashboard", replace: true };
  }
  return true;
});
