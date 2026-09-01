"""
src/live_broker_adapter.py
==========================
Broker adapter scaffold for live algo workflows.

This module intentionally does not place real orders yet.
It provides a stable interface that the UI can call, so broker API
implementations can be plugged in later without refactoring app.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid
from typing import Dict, List, Tuple


BROKER_ENV_VARS: Dict[str, List[str]] = {
    "Groww": ["GROWW_API_KEY", "GROWW_API_SECRET", "GROWW_ACCESS_TOKEN"],
    "Zerodha": ["KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN"],
    "Upstox": ["UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_ACCESS_TOKEN"],
    "Angel One": ["ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_ACCESS_TOKEN"],
    "Dhan": ["DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN"],
    "Other": ["BROKER_API_KEY", "BROKER_API_SECRET", "BROKER_ACCESS_TOKEN"],
}


@dataclass
class StartAlgoRequest:
    broker: str
    symbol: str
    strategy: str
    lots: int
    lot_size: int
    expiry: str
    legs: List[dict]
    stop_loss: float
    target: float
    time_exit_minutes: int
    daily_max_loss_inr: float


class LiveBrokerAdapter:
    """Scaffold adapter with common validation and proxy helpers."""

    def __init__(self, broker: str):
        self.broker = broker if broker in BROKER_ENV_VARS else "Other"

    def required_env_vars(self) -> List[str]:
        return BROKER_ENV_VARS.get(self.broker, BROKER_ENV_VARS["Other"])

    def credentials_ready(self, env_values: Dict[str, str], manual_ready: bool = False) -> bool:
        env_ready = all(bool(env_values.get(k, "")) for k in self.required_env_vars())
        return bool(env_ready or manual_ready)

    def serialize_order_payload(self, req: StartAlgoRequest) -> Dict:
        units_per_leg = int(req.lot_size) * int(req.lots)
        return {
            "broker": self.broker,
            "symbol": req.symbol,
            "strategy": req.strategy,
            "expiry": req.expiry,
            "risk": {
                "stop_loss": float(req.stop_loss),
                "target": float(req.target),
                "time_exit_minutes": int(req.time_exit_minutes),
                "daily_max_loss_inr": float(req.daily_max_loss_inr),
            },
            "orders": [
                {
                    "action": leg.get("action"),
                    "option_type": leg.get("option_type"),
                    "strike": int(leg.get("strike", 0)),
                    "qty_units": units_per_leg,
                }
                for leg in req.legs
            ],
        }

    def build_broker_payload(self, req: StartAlgoRequest) -> Dict:
        """Broker-neutral payload (override in broker-specific subclasses)."""
        return self.serialize_order_payload(req)

    def check_session(self, api_key: str, access_token: str) -> Dict:
        """Basic local session validation scaffold.

        Real implementations should call broker auth/session endpoint.
        """
        ok = bool(api_key and access_token)
        return {
            "ok": ok,
            "status": "scaffold_ok" if ok else "missing_credentials",
            "message": "Session validated by scaffold checks only." if ok else "API key/access token missing.",
        }

    def estimate_margin_proxy(self, strategy: str, legs: List[dict], lot_size: int, lots: int, entry_ref: float) -> Dict[str, float | str]:
        units = max(1, int(lot_size) * int(lots))

        ce_sells = [int(l["strike"]) for l in legs if l.get("option_type") == "CE" and l.get("action") == "SELL"]
        ce_buys = [int(l["strike"]) for l in legs if l.get("option_type") == "CE" and l.get("action") == "BUY"]
        pe_sells = [int(l["strike"]) for l in legs if l.get("option_type") == "PE" and l.get("action") == "SELL"]
        pe_buys = [int(l["strike"]) for l in legs if l.get("option_type") == "PE" and l.get("action") == "BUY"]

        if strategy == "Iron Condor (Defined Risk)" and ce_sells and ce_buys and pe_sells and pe_buys:
            width = max(abs(ce_buys[0] - ce_sells[0]), abs(pe_sells[0] - pe_buys[0]))
            return {"model": "Defined-risk spread width proxy", "proxy_margin": round(width * units, 0)}

        if strategy in ("Bull Put Spread", "Bear Call Spread", "Hedging"):
            if ce_sells and ce_buys:
                width = abs(ce_buys[0] - ce_sells[0])
            elif pe_sells and pe_buys:
                width = abs(pe_sells[0] - pe_buys[0])
            else:
                width = 0
            # Est. margin = max possible loss (spread width - premium received) × units
            net_credit_ref = max(float(entry_ref), 0.0)
            max_loss_per_unit = max(width - net_credit_ref, 0.0)
            return {"model": "Defined-risk spread max-loss proxy",
                    "proxy_margin": round(max_loss_per_unit * units, 0)}

        if strategy == "Short Strangle" and ce_sells and pe_sells:
            avg_notional = ((ce_sells[0] + pe_sells[0]) / 2.0) * units
            return {"model": "Notional x 20% proxy", "proxy_margin": round(avg_notional * 0.20, 0)}

        return {"model": "Premium paid proxy", "proxy_margin": round(max(float(entry_ref), 0.0) * units, 0)}

    def validate_start_request(self, req: StartAlgoRequest) -> Tuple[bool, List[str]]:
        issues: List[str] = []
        if not req.expiry:
            issues.append("Expiry is empty")
        if req.lots <= 0:
            issues.append("Lots must be > 0")
        if req.lot_size <= 0:
            issues.append("Lot size must be > 0")
        if req.stop_loss <= 0 or req.target <= 0:
            issues.append("SL/Target must be > 0")
        if req.time_exit_minutes <= 0:
            issues.append("Time exit must be > 0")
        if not req.legs:
            issues.append("No legs configured")
        return (len(issues) == 0, issues)

    def start_algo(self, req: StartAlgoRequest) -> Dict[str, str | bool | int]:
        ok, issues = self.validate_start_request(req)
        if not ok:
            return {
                "ok": False,
                "status": "validation_failed",
                "message": " | ".join(issues),
            }

        payload = self.build_broker_payload(req)
        intent_id = f"intent_{uuid.uuid4().hex[:12]}"

        return {
            "ok": True,
            "status": "scaffold_only",
            "message": "Start request accepted by adapter scaffold. Real broker routing not implemented yet.",
            "legs": len(req.legs),
            "intent_id": intent_id,
            "payload": payload,
        }

    def place_basket_order(self, req: StartAlgoRequest, dry_run: bool = True) -> Dict:
        """Create broker basket order intent.

        Real implementations should place actual basket order and return broker order IDs.
        """
        started = self.start_algo(req)
        if not started.get("ok"):
            return {
                "ok": False,
                "status": "validation_failed",
                "message": started.get("message", "Validation failed"),
            }

        return {
            "ok": True,
            "status": "dry_run_intent" if dry_run else "scaffold_submit",
            "message": "Basket order intent prepared (no live transmission).",
            "intent_id": started.get("intent_id"),
            "payload": started.get("payload"),
            "dry_run": bool(dry_run),
        }

    def square_off_all(self, symbol: str, strategy: str = "") -> Dict:
        """Create square-off intent scaffold."""
        return {
            "ok": True,
            "status": "scaffold_squareoff_intent",
            "message": "Square-off intent captured (no live transmission).",
            "symbol": symbol,
            "strategy": strategy,
            "intent_id": f"sqoff_{uuid.uuid4().hex[:12]}",
        }

    def get_order_status(self, intent_id: str) -> Dict:
        """Return scaffold order status by intent id."""
        if not intent_id:
            return {
                "ok": False,
                "status": "missing_intent_id",
                "message": "Intent ID is empty.",
            }
        return {
            "ok": True,
            "status": "scaffold_pending",
            "message": "No broker polling wired yet; this is a scaffold status.",
            "intent_id": intent_id,
        }

    def get_leg_ltps(self, symbol: str, expiry: str, legs: List[dict]) -> Dict:
        """Return live LTPs per leg. Base adapters don't support quotes."""
        return {"ok": False, "ltps": {}, "message": f"{self.broker}: live quotes not supported."}


class GrowwLiveBrokerAdapter(LiveBrokerAdapter):
    """Groww-specific payload serializer scaffold."""

    def __init__(self, api_key: str = "", api_secret: str = "", access_token: str = "", allow_live: bool = False):
        super().__init__("Groww")
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._allow_live = bool(allow_live)
        self._transport = None

    def _get_transport(self):
        if self._transport is None:
            from src.groww_transport import build_transport
            self._transport = build_transport(
                self._api_key, self._api_secret, self._access_token, allow_live=self._allow_live
            )
        return self._transport

    def _build_trading_symbol(self, symbol: str, expiry: str, strike: int, option_type: str) -> str:
        """Resolve a Groww F&O trading symbol.

        Prefers an exact match from the cached instruments master. Falls back to
        a best-effort composed symbol (which MUST be validated before live use)
        if the instruments cache is unavailable or has no match.
        """
        try:
            from src.groww_instruments import resolve_trading_symbol
            res = resolve_trading_symbol(symbol, expiry, strike, option_type)
            if res.get("ok") and res.get("trading_symbol"):
                return res["trading_symbol"]
        except Exception:
            pass

        exp_token = ""
        try:
            from datetime import datetime as _dt
            d = _dt.strptime(expiry, "%Y-%m-%d")
            exp_token = d.strftime("%d%b%y").upper()  # e.g. 30JAN25
        except Exception:
            exp_token = (expiry or "").replace("-", "").upper()
        return f"{symbol}{exp_token}{int(strike)}{option_type}"

    def build_broker_payload(self, req: StartAlgoRequest) -> Dict:
        base = self.serialize_order_payload(req)
        groww_orders = []
        for o in base["orders"]:
            groww_orders.append(
                {
                    # Fields consumed by GrowwTransport leg mappers:
                    "trading_symbol": self._build_trading_symbol(
                        base["symbol"], base["expiry"], o["strike"], o["option_type"]
                    ),
                    "action": o["action"],
                    "transaction_type": o["action"],
                    "qty_units": o["qty_units"],
                    "quantity": o["qty_units"],
                    "product": "NRML",
                    "order_type": "MARKET",
                    "validity": "DAY",
                    "exchange": "NSE",
                    "segment": "FNO",
                    # Retained for readability / audit:
                    "option_type": o["option_type"],
                    "strike": o["strike"],
                }
            )
        return {
            "broker": "Groww",
            "symbol": base["symbol"],
            "expiry": base["expiry"],
            "strategy": base["strategy"],
            "risk": base["risk"],
            "basketOrders": groww_orders,
        }

    def check_session(self, api_key: str, access_token: str) -> Dict:
        key = api_key or self._api_key
        token = access_token or self._access_token
        if not (key and token):
            return {
                "ok": False,
                "status": "groww_missing_credentials",
                "message": "Groww API key/access token missing.",
            }
        self._api_key = key
        self._access_token = token
        self._transport = None  # rebuild with latest creds
        res = self._get_transport().validate_session()
        return {
            "ok": bool(res.get("ok")),
            "status": "groww_session_checked",
            "message": res.get("message", "Groww session validated."),
            "transport": res,
        }

    def mint_access_token(self, key_type: str = "approval", totp: str = "", allow_live: bool = False) -> Dict:
        """Generate a Groww access token from API key + secret (approval) or TOTP.

        Requires allow_live=True to perform a real network call; otherwise returns
        the built request in dry-run form.
        """
        if not (self._api_key and self._api_secret):
            return {"ok": False, "status": "missing_key_secret",
                    "message": "API key and secret are required to mint an access token."}
        self._allow_live = bool(allow_live)
        self._transport = None
        transport = self._get_transport()
        res = transport.mint_access_token(key_type=key_type, totp=totp)
        # Propagate any minted token back to the adapter.
        if getattr(transport.creds, "access_token", ""):
            self._access_token = transport.creds.access_token
        return {
            "ok": bool(res.get("ok")),
            "status": "token_minted" if res.get("ok") else "token_failed",
            "message": res.get("message", "Token request completed."),
            "has_token": bool(self._access_token),
            "transport": res,
        }

    def place_basket_order(self, req: StartAlgoRequest, dry_run: bool = True) -> Dict:
        base = super().place_basket_order(req, dry_run=dry_run)
        if not base.get("ok"):
            return base
        # Only allow live transport when explicitly not a dry run AND allow_live enabled.
        self._allow_live = (not dry_run) and self._allow_live
        self._transport = None
        transport = self._get_transport()
        payload = self.build_broker_payload(req)
        transport_res = transport.place_basket(payload)
        base["transport"] = transport_res
        base["message"] = transport_res.get("message", base.get("message"))
        # Surface per-leg order references for reconciliation/polling.
        leg_refs = []
        for lr in transport_res.get("legs", []):
            data = lr.get("data", {}) if isinstance(lr, dict) else {}
            payload_data = data.get("payload", {}) if isinstance(data, dict) else {}
            leg_refs.append({
                "groww_order_id": payload_data.get("groww_order_id"),
                "order_reference_id": (lr.get("request", {}).get("body", {}) or {}).get("order_reference_id")
                    if isinstance(lr.get("request"), dict) else None,
                "ref_id": lr.get("ref_id"),
                "ok": lr.get("ok"),
            })
        base["leg_refs"] = leg_refs
        return base

    def square_off_all(self, symbol: str, strategy: str = "") -> Dict:
        base = super().square_off_all(symbol, strategy)
        transport_res = self._get_transport().square_off(symbol, strategy)
        base["transport"] = transport_res
        base["message"] = transport_res.get("message", base.get("message"))
        return base

    def get_order_status(self, intent_id: str) -> Dict:
        base = super().get_order_status(intent_id)
        if not base.get("ok"):
            return base
        transport_res = self._get_transport().order_status(intent_id)
        base["transport"] = transport_res
        base["message"] = transport_res.get("message", base.get("message"))
        return base

    def get_leg_ltps(self, symbol: str, expiry: str, legs: List[dict]) -> Dict:
        """Fetch live per-leg LTPs from Groww's live-data API.

        Returns {ok, ltps} where ltps maps "<strike><option_type>" (e.g. "23800PE")
        to the last-traded price. Requires a live-capable transport (allow_live +
        access token); in dry-run this returns ok=False so callers fall back.
        """
        if not legs:
            return {"ok": False, "ltps": {}, "message": "No legs supplied."}
        # Build exchange symbols and remember the mapping back to each leg key.
        sym_to_key: Dict[str, str] = {}
        exchange_symbols = []
        for leg in legs:
            strike = int(leg.get("strike", 0) or 0)
            opt = str(leg.get("option_type", "")).upper()
            if strike <= 0 or opt not in ("CE", "PE"):
                continue
            ts = self._build_trading_symbol(symbol, expiry, strike, opt)
            ex_sym = f"NSE_{ts}"
            sym_to_key[ex_sym] = f"{strike}{opt}"
            exchange_symbols.append(ex_sym)
        if not exchange_symbols:
            return {"ok": False, "ltps": {}, "message": "No valid legs to quote."}
        res = self._get_transport().get_ltp(exchange_symbols, segment="FNO")
        ltps: Dict[str, float] = {}
        for ex_sym, price in (res.get("ltps", {}) or {}).items():
            key = sym_to_key.get(ex_sym)
            if key:
                ltps[key] = float(price)
        return {
            "ok": bool(res.get("ok")) and bool(ltps),
            "ltps": ltps,
            "message": res.get("message", ""),
            "transport": res.get("transport"),
        }


def get_live_broker_adapter(
    broker: str,
    api_key: str = "",
    api_secret: str = "",
    access_token: str = "",
    allow_live: bool = False,
) -> LiveBrokerAdapter:
    if broker == "Groww":
        return GrowwLiveBrokerAdapter(
            api_key=api_key,
            api_secret=api_secret,
            access_token=access_token,
            allow_live=allow_live,
        )
    return LiveBrokerAdapter(broker)


def append_journal_event(event: Dict, journal_path: str = "data/live_algo_journal.jsonl") -> str:
    """Append an execution event to JSONL journal for audit/recovery."""
    path = Path(journal_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")
    return str(path)


def tail_journal(journal_path: str = "data/live_algo_journal.jsonl", limit: int = 20) -> List[Dict]:
    path = Path(journal_path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: List[Dict] = []
    for line in lines[-max(1, limit):]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Persistent live-position run-state
# ---------------------------------------------------------------------------

def load_live_positions(state_path: str = "data/live_algo_positions.json") -> Dict[str, Dict]:
    """Load open live positions keyed by intent_id. Returns {} if none."""
    path = Path(state_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_live_positions(positions: Dict[str, Dict], state_path: str = "data/live_algo_positions.json") -> str:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(positions, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(path)


def upsert_live_position(intent_id: str, record: Dict, state_path: str = "data/live_algo_positions.json") -> Dict[str, Dict]:
    """Create or update a live position entry and persist it."""
    if not intent_id:
        return load_live_positions(state_path)
    positions = load_live_positions(state_path)
    existing = positions.get(intent_id, {})
    merged = {
        **existing,
        **record,
        "intent_id": intent_id,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    if "created_utc" not in merged:
        merged["created_utc"] = merged["updated_utc"]
    positions[intent_id] = merged
    _save_live_positions(positions, state_path)
    return positions


def remove_live_position(intent_id: str, state_path: str = "data/live_algo_positions.json") -> Dict[str, Dict]:
    """Remove a position from the open run-state (e.g., after square-off/close)."""
    positions = load_live_positions(state_path)
    if intent_id in positions:
        positions.pop(intent_id, None)
        _save_live_positions(positions, state_path)
    return positions

