/**
 * Re-exports the core API primitives so domain modules stay decoupled
 * from `src/app/`. Domain API wrappers live in sibling files and import
 * `apiCall` / `ApiError` from here.
 */
export { apiCall, ApiError, NetworkError } from "@/app/frappe";
export type { Credentials } from "@/app/frappe";
