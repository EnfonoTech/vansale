frappe.pages["sf-trading-user-guide"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("SF Trading User Guide"),
		single_column: false,
	});

	page.sidebar.html(
		'<div class="list-sidebar-label">' + __("On this page") + "</div>" +
			'<div class="sf-guide-index text-muted">' + __("Loading…") + "</div>"
	);

	var $body = $('<div class="sf-guide-body" style="max-width: 900px;"></div>').appendTo(page.main);

	frappe.call({
		method:
			"vansale.sf_trading.page.sf_trading_user_guide.sf_trading_user_guide.get_user_guide_markdown",
		callback: function (r) {
			if (!r.message) {
				$body.html('<p class="text-muted">' + __("User guide not found.") + "</p>");
				return;
			}
			render_guide(r.message);
		},
	});

	function render_guide(markdown) {
		// The markdown file ships its own manually-anchored TOC for GitHub;
		// inside the desk we replace it with a live index built from the
		// rendered headings so the two can never drift out of sync.
		var body_md = markdown.replace(/## Table of Contents[\s\S]*?(?=\n## )/, "");
		$body.html(frappe.markdown(body_md));

		var $index = wrapper.find(".sf-guide-index");
		var links = [];
		$body.find("h2, h3").each(function (i) {
			var $heading = $(this);
			var id = "sf-guide-sec-" + i;
			$heading.attr("id", id);
			var css = $heading.is("h3") ? "padding-left: 20px; font-size: 90%;" : "";
			links.push(
				'<a class="list-sidebar-link" style="display:block; ' +
					css +
					'" href="#' +
					id +
					'">' +
					frappe.utils.escape_html($heading.text()) +
					"</a>"
			);
		});
		$index.removeClass("text-muted").html(links.join(""));

		$index.on("click", "a", function (e) {
			e.preventDefault();
			var target = document.getElementById($(this).attr("href").slice(1));
			if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
		});
	}
};
