/**
 * Cache warmup — eager population of the item + customer caches so the
 * PWA boots usable when the device goes offline mid-route.
 *
 * Called from:
 *   - LoginView success (first login, fresh install)
 *   - DashboardView onMounted (every app boot — cheap no-op if recent)
 *   - Online-resume handler (when the device transitions offline→online)
 *
 * Strategy:
 *   - Skip if offline (nothing to warm from).
 *   - Skip if last warm was < 10 min ago (avoid hammering the API on
 *     quick navigation).
 *   - Fire both refreshes in parallel; failures are swallowed — we prefer
 *     the user to see the app than to gate on the warm.
 */
import { refreshCache as refreshCustomers } from "@/api/customer";
import { refreshCache as refreshItems } from "@/api/item";
import { isOnline } from "@/app/online";
import { db } from "./db";

const KV_KEY = "cache.warmedAt";
const MIN_INTERVAL_MS = 10 * 60_000;

async function shouldWarm(force: boolean): Promise<boolean> {
  if (force) return true;
  try {
    const d = await db();
    const last = (await d.get("kv", KV_KEY)) as number | undefined;
    if (!last) return true;
    return Date.now() - last > MIN_INTERVAL_MS;
  } catch {
    return true;
  }
}

async function stampWarm(): Promise<void> {
  try {
    const d = await db();
    await d.put("kv", Date.now(), KV_KEY);
  } catch {
    /* ignore */
  }
}

export interface WarmResult {
  customers: number;
  items: number;
  skipped: boolean;
}

export async function warmCaches(opts: { warehouse?: string; force?: boolean } = {}): Promise<WarmResult> {
  if (!isOnline()) return { customers: 0, items: 0, skipped: true };
  if (!(await shouldWarm(opts.force ?? false))) return { customers: 0, items: 0, skipped: true };

  const [cResult, iResult] = await Promise.allSettled([
    refreshCustomers(),
    refreshItems(opts.warehouse),
  ]);

  const customers = cResult.status === "fulfilled" ? cResult.value.length : 0;
  const items = iResult.status === "fulfilled" ? iResult.value.length : 0;

  if (cResult.status === "fulfilled" || iResult.status === "fulfilled") {
    await stampWarm();
  }
  return { customers, items, skipped: false };
}
