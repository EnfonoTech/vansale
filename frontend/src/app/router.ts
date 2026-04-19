/**
 * Router — hash-based on native (deep routes 404 in the Capacitor
 * WebView's file server otherwise — §3.7 rule 10), path-based on web.
 *
 * Guards:
 *   - Unauthenticated → /login
 *   - Authenticated but stale PIN → /pin (unlock mode)
 */
import { createRouter, createWebHashHistory, createWebHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";
import { useSessionStore } from "@/stores/session";
import { isNative } from "./platform";

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
    path: "/payment/new",
    name: "payment-new",
    component: () => import("@/views/PaymentFormView.vue"),
    meta: { requiresAuth: true, requiresPin: true },
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
];

export const router = createRouter({
  history: isNative() ? createWebHashHistory() : createWebHistory("/vansale/"),
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
