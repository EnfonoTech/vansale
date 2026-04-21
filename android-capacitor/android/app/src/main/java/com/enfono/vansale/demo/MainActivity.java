package com.enfono.vansale.demo;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(android.os.Bundle savedInstanceState) {
        // Register custom plugins BEFORE super.onCreate — Capacitor scans
        // the plugin list during bridge init and silently ignores plugins
        // added after (they exist, but web-side calls throw "not implemented").
        registerPlugin(AndroidPrintPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
