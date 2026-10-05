__version__ = "0.1.0"

# Set up a CA bundle before anything imports aiohttp (see bot/certs.py). Importing it here covers
# every entry point, since Python always imports the package first.
from bot import certs as _certs  # noqa: E402,F401
