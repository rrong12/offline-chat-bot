"""Make HTTPS work on Pythons that ship without root certificates.

The python.org macOS installers don't include a CA bundle until "Install Certificates.command"
is run, so every HTTPS connection (Twitch, the fact APIs) fails certificate checks. When
Python's default CA file is missing, point SSL_CERT_FILE at certifi's bundle. This must run
before aiohttp builds its SSL contexts, so `bot/__main__.py` imports this module first.
"""

from __future__ import annotations

import os
import ssl

import certifi


def ensure_ca_bundle() -> bool:
    """Set SSL_CERT_FILE to certifi's bundle if needed. Returns True if it was set."""
    if os.environ.get("SSL_CERT_FILE"):
        return False
    paths = ssl.get_default_verify_paths()
    if (paths.cafile and os.path.exists(paths.cafile)) or (paths.capath and os.path.isdir(paths.capath)):
        return False
    os.environ["SSL_CERT_FILE"] = certifi.where()
    return True


ensure_ca_bundle()
