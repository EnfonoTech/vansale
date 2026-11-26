/**
 * Where the web app is served. It lives at `/vansale` and, as an alias, at
 * `/sf-connect` (same page and built files, see `vansale/pwa.py`), so the router's
 * base and the service worker's scope follow the path it was opened at.
 */
const ALIAS = "/sf-connect";
const DEFAULT_SCOPE = "/vansale";

/** `/sf-connect` under the alias, else `/vansale` (no trailing slash). */
export function webScope(pathname: string = window.location.pathname): string {
  return pathname === ALIAS || pathname.startsWith(`${ALIAS}/`) ? ALIAS : DEFAULT_SCOPE;
}

/** The same with a trailing slash: the router's history base. */
export function webBase(pathname: string = window.location.pathname): string {
  return `${webScope(pathname)}/`;
}
