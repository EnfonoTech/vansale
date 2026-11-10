// apps/vansale/vansale/public/sf_trading/js/sf_overdue_alert.js
// Overdue-invoice alert: chime + toast + desktop notification.
//
// Listens for the `sf_invoice_overdue_alert` realtime event fired by
// vansale/sf_trading/api/overdue_notifications.py. Same delivery recipe as
// permission_manager's approval chime (shared AudioContext unlocked on first
// click, two-tone chime, Notification API), but with its own event so the
// wording says "overdue invoices" and the click opens the report.
//
// Loaded unbundled via app_include_js, so edits go live without `bench build`.

frappe.provide("sf_trading.overdue_alert");

(function () {
	var REPORT = "Invoice Due and Overdue Report";
	var _ctx = null;

	// ── Shared AudioContext ────────────────────────────────────────────────────
	// Browsers block `new AudioContext()` inside async/socket callbacks (autoplay
	// policy). Create it on a real user gesture and keep it alive.
	function _get_ctx() {
		try {
			var A = window.AudioContext || window.webkitAudioContext;
			if (!A) return null;
			if (!_ctx) _ctx = new A();
			return _ctx;
		} catch (e) {
			return null;
		}
	}

	document.addEventListener("click", function () {
		try {
			var ctx = _get_ctx();
			if (ctx && ctx.state === "suspended") ctx.resume();
		} catch (e) {}
	});

	function _tones(ctx) {
		// Descending two-tone (A5 -> D5) — deliberately different from the
		// ascending approval chime so staff can tell them apart by ear.
		[[880.0, 0], [587.33, 0.22]].forEach(function (tone) {
			var osc = ctx.createOscillator();
			var gain = ctx.createGain();
			osc.connect(gain);
			gain.connect(ctx.destination);
			osc.type = "sine";
			osc.frequency.value = tone[0];
			var t = ctx.currentTime + tone[1];
			gain.gain.setValueAtTime(0, t);
			gain.gain.linearRampToValueAtTime(0.22, t + 0.015);
			gain.gain.exponentialRampToValueAtTime(0.001, t + 0.55);
			osc.start(t);
			osc.stop(t + 0.6);
		});
	}

	function _play() {
		try {
			var ctx = _get_ctx();
			if (!ctx) return;
			if (ctx.state === "running") {
				_tones(ctx);
			} else if (ctx.state === "suspended") {
				ctx.resume().then(function () {
					_tones(ctx);
				}).catch(function () {});
			}
		} catch (e) {}
	}

	function _open_report() {
		frappe.set_route("query-report", REPORT);
	}

	function _desktop_notification(title, body) {
		if (!("Notification" in window)) return;
		if (Notification.permission !== "granted") return;
		try {
			var n = new Notification(title, {
				body: body,
				tag: "sf-overdue-invoices",
				requireInteraction: false,
			});
			n.onclick = function () {
				window.focus();
				_open_report();
				n.close();
			};
		} catch (e) {}
	}

	function _handle(data) {
		data = data || {};
		var body = data.message || __("You have overdue invoices.");

		_play();

		frappe.show_alert(
			{
				message: '<a href="#" class="sf-overdue-link">' + frappe.utils.escape_html(body) + "</a>",
				indicator: "red",
			},
			10
		);
		// Toast text links straight into the report.
		$(document).off("click.sf_overdue").on("click.sf_overdue", ".sf-overdue-link", function (e) {
			e.preventDefault();
			_open_report();
		});

		_desktop_notification(data.title || __("Overdue invoices"), body);
	}

	sf_trading.overdue_alert.handle = _handle;

	// ── Socket listener ────────────────────────────────────────────────────────
	// frappe.realtime exists at bundle-load time but .socket is only set later in
	// desk.js; realtime.on() is a silent no-op until then, so retry until ready.
	(function _setup(attempt) {
		try {
			if (frappe.realtime && frappe.realtime.socket) {
				frappe.realtime.on("sf_invoice_overdue_alert", function (data) {
					try {
						_handle(data);
					} catch (e) {}
				});
				return;
			}
		} catch (e) {}
		if (attempt < 100) {
			setTimeout(function () {
				_setup(attempt + 1);
			}, 300);
		}
	})(0);
})();
