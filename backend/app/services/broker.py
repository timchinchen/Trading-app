from typing import Literal, Optional

from ..config import settings


class BrokerError(Exception):
    pass


class AlpacaBroker:
    """Thin wrapper around alpaca-py TradingClient.

    Mode is locked at construction time. There is no runtime switch.
    Live mode requires real credentials and submits real orders.
    """

    def __init__(self, mode: Literal["paper", "live"]):
        self.mode = mode
        self._client = None
        try:
            from alpaca.trading.client import TradingClient

            key = settings.ALPACA_LIVE_KEY if mode == "live" else settings.ALPACA_PAPER_KEY
            secret = settings.ALPACA_LIVE_SECRET if mode == "live" else settings.ALPACA_PAPER_SECRET
            if key and secret:
                self._client = TradingClient(key, secret, paper=(mode == "paper"))
        except Exception as e:  # pragma: no cover
            print(f"[broker] init warning: {e}")
            self._client = None

    @property
    def configured(self) -> bool:
        return self._client is not None

    # --- Account & positions ---
    def account(self) -> dict:
        if not self._client:
            return {
                "cash": 0.0,
                "buying_power": 0.0,
                "portfolio_value": 0.0,
                "currency": "USD",
                "mode": self.mode,
            }
        a = self._client.get_account()
        return {
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
            "portfolio_value": float(a.portfolio_value),
            "currency": a.currency,
            "mode": self.mode,
        }

    def positions(self) -> list[dict]:
        if not self._client:
            return []
        out = []
        for p in self._client.get_all_positions():
            # Alpaca exposes unrealized_plpc as a decimal string ("0.123" = +12.3%).
            plpc = getattr(p, "unrealized_plpc", None)
            try:
                plpc_f = float(plpc) if plpc is not None else None
            except Exception:
                plpc_f = None
            out.append({
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": plpc_f,
                "current_price": float(p.current_price),
            })
        return out

    # --- Orders ---
    def list_orders(self, status: Optional[str] = None) -> list[dict]:
        if not self._client:
            return []
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        req = None
        if status:
            try:
                req = GetOrdersRequest(status=QueryOrderStatus(status))
            except Exception:
                req = None
        orders = self._client.get_orders(filter=req) if req else self._client.get_orders()
        return [self._order_to_dict(o) for o in orders]

    def place_order(self, symbol: str, qty: float, side: str, type_: str,
                    limit_price: Optional[float] = None) -> dict:
        if not self._client:
            raise BrokerError("Broker not configured. Set Alpaca credentials in .env")
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
        if type_ == "market":
            req = MarketOrderRequest(symbol=symbol, qty=qty, side=side_enum, time_in_force=TimeInForce.DAY)
        else:
            if limit_price is None:
                raise BrokerError("limit_price is required for limit orders")
            req = LimitOrderRequest(symbol=symbol, qty=qty, side=side_enum,
                                    limit_price=limit_price, time_in_force=TimeInForce.DAY)
        o = self._client.submit_order(order_data=req)
        return self._order_to_dict(o)

    def cancel_order(self, alpaca_id: str) -> None:
        if not self._client:
            raise BrokerError("Broker not configured.")
        self._client.cancel_order_by_id(alpaca_id)

    def get_order_by_id(self, alpaca_id: str) -> dict | None:
        """Pull the latest state for a single order. Returns None on any
        error / unconfigured broker so callers can just skip reconciliation."""
        if not self._client:
            return None
        try:
            o = self._client.get_order_by_id(alpaca_id)
        except Exception as e:
            print(f"[broker] get_order_by_id({alpaca_id}) failed: {e}")
            return None
        return self._order_to_dict(o)

    def _order_to_dict(self, o) -> dict:
        def _f(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        return {
            "alpaca_id": str(o.id),
            "symbol": o.symbol,
            "qty": float(o.qty) if o.qty is not None else 0.0,
            "side": o.side.value if hasattr(o.side, "value") else str(o.side),
            "type": o.order_type.value if hasattr(o.order_type, "value") else str(o.order_type),
            "limit_price": _f(getattr(o, "limit_price", None)),
            "status": o.status.value if hasattr(o.status, "value") else str(o.status),
            "submitted_at": o.submitted_at,
            "filled_avg_price": _f(getattr(o, "filled_avg_price", None)),
            "filled_qty": _f(getattr(o, "filled_qty", None)),
            "filled_at": getattr(o, "filled_at", None),
        }

    # --- Quotes ---
    def latest_quote(self, symbol: str) -> dict:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestQuoteRequest

            key = settings.ALPACA_LIVE_KEY if self.mode == "live" else settings.ALPACA_PAPER_KEY
            secret = settings.ALPACA_LIVE_SECRET if self.mode == "live" else settings.ALPACA_PAPER_SECRET
            if not (key and secret):
                return {"symbol": symbol}
            data_client = StockHistoricalDataClient(key, secret)
            r = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
            q = r[symbol]
            return {
                "symbol": symbol,
                "bid": float(q.bid_price) if q.bid_price else None,
                "ask": float(q.ask_price) if q.ask_price else None,
                "last": float(q.ask_price) if q.ask_price else None,
                "ts": q.timestamp,
            }
        except Exception as e:
            print(f"[broker] latest_quote error: {e}")
            return {"symbol": symbol}
