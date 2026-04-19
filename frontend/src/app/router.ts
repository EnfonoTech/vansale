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
