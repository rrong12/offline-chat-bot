"""Make HTTPS work on Pythons that ship without root certificates.

The python.org macOS installers don't include a CA bundle until "Install Certificates.command"
is run, so every HTTPS connection (Twitch, the fact APIs) fails certificate checks. When
Python's default CA file is missing, point SSL_CERT_FILE at certifi's bundle. This must run
before aiohttp builds its SSL contexts, so `bot/__init__.py` imports this module.
"""

from __future__ import annotations

import os
import ssl

import certifi


def _has_certificates(directory: str | None) -> bool:
    if not directory or not os.path.isdir(directory):
        return False
    with os.scandir(directory) as entries:
        return any(True for _ in entries)


def ensure_ca_bundle() -> bool:
    """Set SSL_CERT_FILE to certifi's bundle if needed. Returns True if it was set."""
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return False
    paths = ssl.get_default_verify_paths()  # cafile/capath are None when missing
    if paths.cafile or _has_certificates(paths.capath):
        return False
    os.environ["SSL_CERT_FILE"] = certifi.where()
    return True


USING_CERTIFI = ensure_ca_bundle()
