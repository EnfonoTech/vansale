// Clear the Link control's in-memory autocomplete cache for every item_code
// field across all forms whenever the input gains focus.
// This ensures the item dropdown always fetches fresh sorted results from the
// server rather than showing stale cached results from a previous search.

(function () {
	$(document).on(
		"focusin",
		"[data-fieldname='item_code'] input",
		function () {
			var $input = $(this);
			if ($input[0]) {
				$input[0].cache = {};
			}
		}
	);
})();
