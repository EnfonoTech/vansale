/**
 * Vitest setup. Runs once per worker before any test file imports.
 *
 * `fake-indexeddb/auto` patches global `indexedDB` + `IDBKeyRange`. Each
 * test should clear state via `resetOfflineDb()` from @/test/offline-utils
 * to isolate test runs.
 */
import "fake-indexeddb/auto";
