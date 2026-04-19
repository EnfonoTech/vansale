app_name = "vansale"
app_title = "Van Sale"
app_publisher = "Enfono Technologies"
app_description = "Van Sales PWA — offline-first Vue 3 SPA + Capacitor APK"
app_email = "ramees@enfono.com"
app_license = "mit"

# Hooks that run on migrate. Capacitor CORS is idempotent and critical for APK login.
after_migrate = [
    "vansale.install.ensure_capacitor_cors",
]

# Web redirects — opening `/vansale` loads the built Vue SPA.
website_redirects = [
    {"source": "/vansale", "target": "/assets/vansale/spa/index.html"},
    {"source": "/vansale/", "target": "/assets/vansale/spa/index.html"},
]

# Fixtures exported on `bench export-fixtures --app vansale`.
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "Vansale"]],
    },
]
