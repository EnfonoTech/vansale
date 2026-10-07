app_name = "vansale"
app_title = "Van Sale"
app_publisher = "Enfono Technologies"
app_description = "Van Sales PWA — offline-first Vue 3 SPA + Capacitor APK"
app_email = "ramees@enfono.com"
app_license = "mit"

# Hooks that run on migrate.
# - ensure_capacitor_cors is idempotent and critical for APK login.
# - setup.after_migrate installs the Van User role + its DocPerms and
#   re-applies User Permissions for all Vansale Configuration rows.
after_migrate = [
    "vansale.install.ensure_capacitor_cors",
    "vansale.setup.after_migrate",
]

# /vansale and every /vansale/<path> render www/vansale (the SPA's index.html),
# so the web app has clean URLs and a refresh on a deep link works.
website_route_rules = [
    {"from_route": "/vansale/<path:app_path>", "to_route": "vansale"},
]

# Fixtures exported on `bench export-fixtures --app vansale`.
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "Vansale"]],
    },
]

# Inject Van User defaults + sidebar restrictions into the desk session.
boot_session = "vansale.boot.boot_session"

# Role home page — Van Users land straight on the PWA.
role_home_page = {
    "Van User": "/vansale",
    "Van Manager": "/vansale",
}

# List-view filters — restrict Van Users to docs touching their warehouse.
permission_query_conditions = {
    "Sales Invoice": "vansale.van_filters.sales_invoice_query",
    "Payment Entry": "vansale.van_filters.payment_entry_query",
    "Stock Entry": "vansale.van_filters.stock_entry_query",
    "Delivery Note": "vansale.van_filters.delivery_note_query",
    "Van Visit Log": "vansale.van_filters.van_visit_log_query",
    "Van Daily Visit": "vansale.van_filters.van_daily_visit_query",
}

# Before-validate hooks — force cost_center + warehouse to the user's
# defaults on stock-affecting docs.
doc_events = {
    "Customer": {
        "before_insert": "vansale.customer_hooks.auto_assign_sales_person",
    },
    "Vansale Configuration User": {
        "after_insert": "vansale.customer_hooks.clear_module_active_cache",
        "on_trash": "vansale.customer_hooks.clear_module_active_cache",
    },
    "Sales Invoice": {
        # before_insert, not before_validate: naming_series is consumed when the
        # name is generated at insert, so a later hook would be too late.
        "before_insert": "vansale.van_series.set_naming_series_from_van",
        "before_validate": [
            "vansale.van_defaults.override_cost_center_from_van",
            "vansale.van_defaults.override_warehouse_from_van",
        ],
    },
    "Payment Entry": {
        "before_insert": "vansale.van_series.set_naming_series_from_van",
        "before_validate": "vansale.van_defaults.override_cost_center_from_van",
    },
    "Delivery Note": {
        "before_validate": [
            "vansale.van_defaults.override_cost_center_from_van",
            "vansale.van_defaults.override_warehouse_from_van",
        ],
    },
    "Stock Entry": {
        "before_insert": "vansale.van_series.set_naming_series_from_van",
        "before_validate": "vansale.van_defaults.override_cost_center_from_van",
    },
}
