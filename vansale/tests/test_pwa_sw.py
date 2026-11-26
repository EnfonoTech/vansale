"""The install worker (`vansale.pwa.SW_JS`): it keeps its install / activate /
fetch behaviour and shows an approval push, and a tap on it opens the right
screen. The worker is JavaScript, so besides checking the text this runs it:
when `node` is on the PATH, the worker source is evaluated against a fake
`self`, `clients` and `registration`, the `push` and `notificationclick`
events are fired, and what it does is compared with what it should do.

No site and no browser needed.

Run: cd ~/frappe-bench/sites && PYTHONPATH=$HOME/dev/vansale \
     ../env/bin/python -m unittest vansale.tests.test_pwa_sw -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from vansale import pwa

ORIGIN = "https://erp.example.com"
APPROVALS = f"{ORIGIN}/vansale/approvals"

# Reads {"sw": <worker source>, "cases": [...]} on stdin, runs every case in a
# fresh copy of the worker and prints one result per case as JSON.
HARNESS = r"""
const vm = require("node:vm");
const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));

function build(origin, windows, navigateFails) {
  const listeners = {};
  const log = { shown: [], opened: [], closed: 0, navigated: [], focused: [], matchAll: [] };
  const mkWindow = (url) => ({
    url,
    navigate: (target) =>
      navigateFails
        ? Promise.reject(new TypeError("not controlled"))
        : (log.navigated.push(target), Promise.resolve(mkWindow(target))),
    focus() { log.focused.push(this.url); return Promise.resolve(this); },
  });
  const self = {
    location: { origin },
    addEventListener: (type, fn) => { listeners[type] = fn; },
    skipWaiting: () => {},
    clients: {
      claim: () => {},
      matchAll: (options) => { log.matchAll.push(options); return Promise.resolve(windows.map(mkWindow)); },
      openWindow: (target) => { log.opened.push(target); return Promise.resolve(null); },
    },
    registration: {
      showNotification: (title, options) => { log.shown.push({ title, options }); return Promise.resolve(); },
    },
  };
  vm.runInNewContext(input.sw, { self, URL, Response: class {} });
  return { listeners, log };
}

async function run(testCase) {
  const { listeners, log } = build(testCase.origin, testCase.windows || [], testCase.navigateFails);
  const waited = [];
  const event = { waitUntil: (p) => waited.push(p) };
  if (testCase.kind === "push") {
    event.data = testCase.data === undefined ? null : {
      json: () => { if (testCase.data === "BAD") throw new SyntaxError("bad"); return testCase.data; },
    };
    listeners.push(event);
  } else {
    event.notification = { close: () => { log.closed++; }, data: testCase.notificationData };
    listeners.notificationclick(event);
  }
  await Promise.all(waited);
  return { log, handlers: Object.keys(listeners).sort(), waited: waited.length };
}

(async () => {
  const out = [];
  for (const testCase of input.cases) out.push(await run(testCase));
  process.stdout.write(JSON.stringify(out));
})().catch((error) => { console.error(error); process.exit(1); });
"""


def run_worker(cases: list[dict]) -> list[dict]:
    done = subprocess.run(
        ["node", "-e", HARNESS],
        input=json.dumps({"sw": pwa.SW_JS, "cases": cases}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if done.returncode != 0:
        raise AssertionError(f"node failed: {done.stderr}")
    return json.loads(done.stdout)


def click(data, windows=(), navigate_fails=False) -> dict:
    return {
        "kind": "click",
        "origin": ORIGIN,
        "notificationData": data,
        "windows": list(windows),
        "navigateFails": navigate_fails,
    }


def push(data="__none__") -> dict:
    case = {"kind": "push", "origin": ORIGIN}
    if data != "__none__":
        case["data"] = data
    return case


class TestWorkerText(unittest.TestCase):
    """The text of the worker: what has to be there whether or not node is."""

    def test_keeps_install_activate_and_fetch(self):
        self.assertIn('self.addEventListener("install", () => self.skipWaiting())', pwa.SW_JS)
        self.assertIn('self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()))', pwa.SW_JS)
        self.assertIn('self.addEventListener("fetch"', pwa.SW_JS)
        self.assertIn('event.request.mode !== "navigate"', pwa.SW_JS)
        self.assertIn("No connection", pwa.SW_JS)

    def test_has_the_push_and_notificationclick_handlers(self):
        self.assertIn('self.addEventListener("push"', pwa.SW_JS)
        self.assertIn('self.addEventListener("notificationclick"', pwa.SW_JS)
        self.assertIn("self.registration.showNotification", pwa.SW_JS)
        self.assertIn("event.notification.close()", pwa.SW_JS)
        self.assertIn("includeUncontrolled: true", pwa.SW_JS)
        self.assertIn("openWindow", pwa.SW_JS)
        self.assertIn('"/vansale/icon-192.png"', pwa.SW_JS)

    def test_only_a_path_under_vansale_on_the_same_origin_is_followed(self):
        self.assertIn('url.origin === origin && url.pathname.startsWith("/vansale/")', pwa.SW_JS)
        self.assertIn('origin + "/vansale/approvals"', pwa.SW_JS)

    def test_the_worker_is_served_from_the_sw_path_with_the_scope_header(self):
        renderer = object.__new__(pwa.VansalePWARenderer)
        renderer.path = "/vansale/sw.js"
        self.assertTrue(renderer.can_render())
        response = renderer.render()
        self.assertEqual(response.get_data(as_text=True), pwa.SW_JS)
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/vansale")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestWorkerBehaviour(unittest.TestCase):
    """The worker run for real against fakes."""

    def test_the_worker_registers_every_handler_it_should(self):
        (result,) = run_worker([push({"title": "x"})])
        self.assertEqual(result["handlers"], ["activate", "fetch", "install", "notificationclick", "push"])

    # push ------------------------------------------------------------------

    def test_a_push_shows_its_title_body_tag_and_the_url_to_open(self):
        (result,) = run_worker(
            [
                push(
                    {
                        "title": "Approval needed",
                        "body": "Sales Invoice SINV-0001",
                        "url": "/vansale/approvals/Sales%20Invoice/SINV-0001",
                        "tag": "PMWA-1",
                    }
                )
            ]
        )
        self.assertEqual(result["waited"], 1)  # the page of the browser is held until it shows
        self.assertEqual(
            result["log"]["shown"],
            [
                {
                    "title": "Approval needed",
                    "options": {
                        "body": "Sales Invoice SINV-0001",
                        "tag": "PMWA-1",
                        "data": {"url": "/vansale/approvals/Sales%20Invoice/SINV-0001"},
                        "icon": "/vansale/icon-192.png",
                    },
                }
            ],
        )

    def test_a_push_with_nothing_readable_still_shows_a_default_notification(self):
        # A browser that gets a push and shows nothing may cancel the subscription.
        for case in (push("BAD"), push(), push(None), push("text"), push(5)):
            with self.subTest(case=case):
                (result,) = run_worker([case])
                self.assertEqual(result["waited"], 1)
                (shown,) = result["log"]["shown"]
                self.assertEqual(shown["title"], "Approval needed")
                self.assertEqual(shown["options"]["body"], "")
                self.assertEqual(shown["options"]["data"], {"url": "/vansale/approvals"})
                self.assertEqual(shown["options"]["icon"], "/vansale/icon-192.png")

    # notificationclick -----------------------------------------------------

    def test_a_tap_closes_the_notification_and_opens_the_document_when_no_window_is_open(self):
        (result,) = run_worker([click({"url": "/vansale/approvals/Sales%20Invoice/SINV-0001"})])
        log = result["log"]
        self.assertEqual(log["closed"], 1)
        self.assertEqual(log["opened"], [f"{ORIGIN}/vansale/approvals/Sales%20Invoice/SINV-0001"])
        self.assertEqual(log["matchAll"], [{"type": "window", "includeUncontrolled": True}])

    def test_a_tap_moves_an_open_window_of_the_app_to_the_document_and_focuses_it(self):
        target = f"{ORIGIN}/vansale/approvals/Journal%20Entry/JV-1"
        (result,) = run_worker(
            [click({"url": "/vansale/approvals/Journal%20Entry/JV-1"}, windows=[f"{ORIGIN}/vansale/dashboard"])]
        )
        log = result["log"]
        self.assertEqual(log["navigated"], [target])
        self.assertEqual(log["focused"], [target])
        self.assertEqual(log["opened"], [])

    def test_a_tap_ignores_windows_that_are_not_the_app(self):
        (result,) = run_worker(
            [
                click(
                    {"url": "/vansale/approvals"},
                    windows=[f"{ORIGIN}/app/home", "https://elsewhere.example/vansale/x"],
                )
            ]
        )
        self.assertEqual(result["log"]["navigated"], [])
        self.assertEqual(result["log"]["opened"], [APPROVALS])

    def test_a_tap_opens_a_new_window_when_the_open_one_cannot_be_moved(self):
        # An uncontrolled window refuses `navigate`.
        (result,) = run_worker(
            [click({"url": "/vansale/approvals"}, windows=[f"{ORIGIN}/vansale/more"], navigate_fails=True)]
        )
        self.assertEqual(result["log"]["opened"], [APPROVALS])

    def test_a_tap_never_leaves_the_app(self):
        refused = [
            "https://evil.example/vansale/approvals",  # another origin
            "//evil.example/vansale/approvals",  # protocol-relative
            "/\\evil.example/vansale/approvals",  # a backslash is a slash to a URL parser
            "http://erp.example.com/vansale/approvals",  # same host, other scheme = other origin
            "/other",  # this origin, not this app
            "/vansale",  # no trailing slash: not under /vansale/
            "/vansaleX/approvals",
            "/vansale/../desk",  # climbs out
            "/vansale/%2e%2e/desk",
            "javascript:alert(1)",
            "data:text/html,x",
            "",
            None,
            "https://",
        ]
        for url in refused:
            with self.subTest(url=url):
                (result,) = run_worker([click({"url": url})])
                self.assertEqual(result["log"]["opened"], [APPROVALS])

    def test_a_tap_with_no_data_at_all_opens_the_approvals_list(self):
        (result,) = run_worker([click(None)])
        self.assertEqual(result["log"]["opened"], [APPROVALS])
        self.assertEqual(result["log"]["closed"], 1)

    def test_a_tap_keeps_the_query_of_an_app_path(self):
        (result,) = run_worker([click({"url": "/vansale/approvals?tab=history"})])
        self.assertEqual(result["log"]["opened"], [f"{ORIGIN}/vansale/approvals?tab=history"])


if __name__ == "__main__":
    unittest.main()
