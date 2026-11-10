// apps/vansale/vansale/public/sf_trading/js/workflow_approval_shortcut.js
// Adds a pending count badge next to the "Work Flow Approval" shortcut
// on any workspace, matching the native ERPNext shortcut count style.

frappe.provide("sf_trading.wf_shortcut");

sf_trading.wf_shortcut.update_count = function() {
    let $links = $('.shortcut-widget-box a, .widget.shortcut-widget-box .widget-title')
        .filter(function() {
            return $(this).text().trim().toLowerCase().includes("work flow approval")
                || $(this).text().trim().toLowerCase().includes("workflow approval");
        });

    if (!$links.length) return;

    frappe.call({
        method: "vansale.sf_trading.report.work_flow_approval.work_flow_approval.get_pending_approval_count",
        callback: function(r) {
            let count = r.message || 0;

            $('.shortcut-widget-box').each(function() {
                let $box = $(this);
                let txt = $box.find('.widget-title, a').first().text().trim().toLowerCase();
                if (!txt.includes("work flow approval") && !txt.includes("workflow approval")) return;

                // Remove any previous injected badge
                $box.find('.wf-pending-count').remove();

                // Build badge in the same style as ERPNext's native shortcut count
                let $badge = $(`<span class="wf-pending-count" style="
                    display:inline-block;
                    margin-left:8px;
                    padding:2px 8px;
                    background:#f4f5f6;
                    color:${count > 0 ? '#e24c4c' : '#525252'};
                    border-radius:8px;
                    font-size:12px;
                    font-weight:500;
                    vertical-align:middle;
                ">${count}</span>`);

                // Append to the title/link
                let $target = $box.find('.widget-title').first();
                if (!$target.length) $target = $box.find('a').first();
                $target.append($badge);
            });
        }
    });
};

// Run after route changes (workspace navigation) and on initial load
$(document).on("page-change app_ready", function() {
    setTimeout(sf_trading.wf_shortcut.update_count, 600);
    setTimeout(sf_trading.wf_shortcut.update_count, 1500); // retry for slow loads
});

frappe.after_ajax(function() {
    setTimeout(sf_trading.wf_shortcut.update_count, 1000);
});

// Refresh every 60 seconds while the page is open
setInterval(sf_trading.wf_shortcut.update_count, 60000);