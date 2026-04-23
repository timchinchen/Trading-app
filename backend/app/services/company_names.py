"""Resolve a ticker symbol to a human-readable company / fund name.

Primary source: SEC's `company_tickers.json`, already cached in memory by
`services.agent.intel.sec_edgar._load_ticker_map`. That covers every US
equity filer but *not* ETFs, which don't file their own 10-K.

So we layer a small static fallback for the ETFs we see on most
watchlists. If neither source knows the symbol we return None and the
frontend falls back to showing the ticker itself as the hover tip.

Design notes:
- No new HTTP on the hot path for the dashboard: `prefetch_names` loads
  the SEC map once and then `lookup` is pure-dict.
- Swallow all errors. A missing name is cosmetic, not a crash.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .agent.intel import sec_edgar

# ETFs and common funds that the SEC filer map doesn't cover well. Keep
# this small - just the tickers people actually see day to day.
_STATIC_NAMES: dict[str, str] = {
    # Broad market
    "SPY": "SPDR S&P 500 ETF",
    "VOO": "Vanguard S&P 500 ETF",
    "IVV": "iShares Core S&P 500 ETF",
    "VTI": "Vanguard Total Stock Market ETF",
    "QQQ": "Invesco QQQ Trust (Nasdaq-100)",
    "DIA": "SPDR Dow Jones Industrial Average ETF",
    "IWM": "iShares Russell 2000 ETF",
    # Sectors
    "XLK": "Technology Select Sector SPDR",
    "XLF": "Financial Select Sector SPDR",
    "XLE": "Energy Select Sector SPDR",
    "XLV": "Health Care Select Sector SPDR",
    "XLY": "Consumer Discretionary Select Sector SPDR",
    "XLP": "Consumer Staples Select Sector SPDR",
    "XLI": "Industrial Select Sector SPDR",
    "XLU": "Utilities Select Sector SPDR",
    "XLB": "Materials Select Sector SPDR",
    "XLRE": "Real Estate Select Sector SPDR",
    # Commodities / oil
    "USO": "United States Oil Fund",
    "UNG": "United States Natural Gas Fund",
    "GLD": "SPDR Gold Shares",
    "SLV": "iShares Silver Trust",
    # Bonds / treasuries
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "IEF": "iShares 7-10 Year Treasury Bond ETF",
    "SHY": "iShares 1-3 Year Treasury Bond ETF",
    "HYG": "iShares iBoxx $ High Yield Corporate Bond ETF",
    # Volatility / leveraged
    "VXX": "iPath S&P 500 VIX Short-Term Futures ETN",
    "TQQQ": "ProShares UltraPro QQQ (3x Nasdaq-100)",
    "SQQQ": "ProShares UltraPro Short QQQ (-3x Nasdaq-100)",
    "SPXL": "Direxion Daily S&P 500 Bull 3X",
    "SPXS": "Direxion Daily S&P 500 Bear 3X",
    # International / emerging
    "EFA": "iShares MSCI EAFE ETF",
    "EEM": "iShares MSCI Emerging Markets ETF",
    "VEA": "Vanguard FTSE Developed Markets ETF",
    "VWO": "Vanguard FTSE Emerging Markets ETF",
    # Thematic
    "ARKK": "ARK Innovation ETF",
    "SMH": "VanEck Semiconductor ETF",
    "SOXX": "iShares Semiconductor ETF",
    "IBIT": "iShares Bitcoin Trust",
    "GBTC": "Grayscale Bitcoin Trust",
}


async def prefetch_names(symbols: Iterable[str], *, user_agent: str) -> None:
    """Warm the SEC ticker map if any symbol might need it.

    Cheap to call - after the first successful load it's a dict check on
    the already-populated module-level cache inside `sec_edgar`.
    """
    syms = [s.upper() for s in symbols if s]
    if not syms:
        return
    # Only touch the network if at least one symbol isn't in the static
    # override (ETFs etc. are satisfied without SEC).
    if all(s in _STATIC_NAMES for s in syms):
        return
    if not user_agent:
        return
    try:
        await sec_edgar._load_ticker_map(user_agent)
    except Exception:
        # _load_ticker_map already logs its own error; don't surface.
        pass


def lookup(symbol: str) -> Optional[str]:
    """Return a best-effort company/fund name, or None."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return None
    # Static first so ETFs resolve even if SEC is offline.
    if sym in _STATIC_NAMES:
        return _STATIC_NAMES[sym]
    try:
        name = sec_edgar.lookup_name(sym)
    except Exception:
        name = None
    return name or None


def lookup_many(symbols: Iterable[str]) -> dict[str, str]:
    """Bulk resolve. Missing symbols are simply absent from the result."""
    out: dict[str, str] = {}
    for s in symbols:
        name = lookup(s)
        if name:
            out[s.upper().strip()] = name
    return out
