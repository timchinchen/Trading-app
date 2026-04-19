"""Market-intelligence scrapers used to corroborate Twitter-derived signals.

Each submodule exposes an async function that returns a dict with a stable
shape. Failures are NEVER raised - they return an empty payload plus an
`error` key so the caller can keep running when a source is down.
"""
from .aggregator import collect_intel, MarketIntel  # noqa: F401
from . import fmp, sec_edgar  # noqa: F401
