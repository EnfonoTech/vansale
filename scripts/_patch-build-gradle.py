#!/usr/bin/env python3
"""Wire release signing into android/app/build.gradle.

REPLACES the default release buildType — never appends (fatehhr lesson
§5.1). Run by build-customer.sh after `npx cap copy android`.

Inputs (env):
    VANSALE_KEYSTORE_PATH  absolute path to the keystore
    VANSALE_KEYSTORE_ALIAS usually  vansale-<customer>
    (passwords come from env at Gradle invocation)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BUILD_GRADLE = Path(sys.argv[1] if len(sys.argv) > 1 else "android-capacitor/android/app/build.gradle")
KEYSTORE_PATH = os.environ.get("VANSALE_KEYSTORE_PATH", "")
ALIAS = os.environ.get("VANSALE_KEYSTORE_ALIAS", "vansale-demo")
APP_ID = os.environ.get("CUSTOMER_APP_ID", "com.enfono.vansale.demo")

if not BUILD_GRADLE.exists():
    print(f"✗ Not found: {BUILD_GRADLE}", file=sys.stderr)
    sys.exit(1)

src = BUILD_GRADLE.read_text()

# 1. Swap applicationId
src = re.sub(
    r'applicationId\s+"[^"]+"',
    f'applicationId "{APP_ID}"',
    src,
)

# 2. Ensure signingConfigs block exists and has our `release` entry.
signing_block = f"""
    signingConfigs {{
        release {{
            def pw = System.getenv('VANSALE_KEYSTORE_PW') ?: ''
            storeFile file('{KEYSTORE_PATH}')
            storePassword pw
            keyAlias '{ALIAS}'
            keyPassword pw
            storeType 'pkcs12'
        }}
    }}
""".strip()

if "signingConfigs" in src:
    src = re.sub(
        r"signingConfigs\s*\{[^}]*release\s*\{[^}]*\}\s*\}",
        signing_block,
        src,
        flags=re.DOTALL,
        count=1,
    )
else:
    # Inject inside android { ... }
    src = re.sub(
        r"android\s*\{",
        f"android {{\n    {signing_block}",
        src,
        count=1,
    )

# 3. Replace default release buildType (don't append — avoids duplicates).
release_block = """
        release {
            signingConfig signingConfigs.release
            minifyEnabled false
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
        }
""".rstrip()
src = re.sub(
    r"release\s*\{[^}]*\}",
    release_block.strip(),
    src,
    count=1,
    flags=re.DOTALL,
)

BUILD_GRADLE.write_text(src)
print(f"✓ Patched {BUILD_GRADLE}")
