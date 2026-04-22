/**
 * Test helpers for offline/* modules.
 *
 * `resetOfflineDb()` drops the IDB database AND resets the module-local
 * `_dbPromise` so the next `db()` call reopens + re-runs `upgrade`.
 * Keeps tests hermetic without bleeding state across files.
 */
import { __resetDbForTests } from "@/offline/db";

export async function resetOfflineDb(): Promise<void> {
  await __resetDbForTests();
}
