"""
src/groww_transport.py
======================
Groww Trading API transport layer.

Contract source: https://groww.in/trade-api/docs/curl
- Base URL: https://api.groww.in
- Mandatory headers on every request:
    Authorization: Bearer {ACCESS_TOKEN}
    Accept: application/json
    X-API-VERSION: 1.0
- Order placement is per-order (no native multi-leg basket placement endpoint).
  A basket is placed by sending each leg to /v1/order/create sequentially.
- Basket margin IS supported via POST /v1/margins/detail/orders (FNO/COMMODITY).

SAFETY:
- No real network request is sent unless allow_live=True AND a valid access
  token is present AND the `requests` library is available. Default is dry-run:
  requests are fully built and returned as simulated responses so field/endpoint
  mapping can be verified without transmitting anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
import hashlib
import time
import uuid


GROWW_BASE_URL = "https://api.groww.in"
GROWW_API_VERSION = "1.0"

GROWW_ENDPOINTS = {
    "token": "/v1/token/api/access",
    "user_margin": "/v1/margins/detail/user",
    "basket_margin": "/v1/margins/detail/orders",   # POST, ?segment=FNO
    "order_create": "/v1/order/create",             # POST
    "order_modify": "/v1/order/modify",             # POST
    "order_cancel": "/v1/order/cancel",             # POST
    "order_status": "/v1/order/status",             # GET /{groww_order_id}?segment=FNO
    "order_list": "/v1/order/list",                 # GET ?segment=FNO
    "ltp": "/v1/live-data/ltp",                     # GET ?segment=FNO&exchange_symbols=NSE_...
}


def generate_checksum(secret: str, timestamp: str) -> str:
    """SHA-256 of (secret + timestamp) per Groww auth spec."""
    return hashlib.sha256((secret + timestamp).encode("utf-8")).hexdigest()


@dataclass
class GrowwCredentials:
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""

    def is_ready(self) -> bool:
        # A ready session needs either an access token, or key+secret to mint one.
        return bool(self.access_token or (self.api_key and self.api_secret))


@dataclass
class GrowwTransport:
    creds: GrowwCredentials
    allow_live: bool = False
    segment: str = "FNO"
    exchange: str = "NSE"
    timeout_sec: int = 10

    # -- Header / request building --------------------------------------

    def _base_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.creds.access_token}",
            "X-API-VERSION": GROWW_API_VERSION,
        }

    def _post_headers(self) -> Dict[str, str]:
        h = self._base_headers()
        h["Content-Type"] = "application/json"
        return h

    def _request(self, method: str, endpoint_key: str, path_suffix: str = "",
                 query: Optional[Dict] = None, body=None) -> Dict:
        """Central request wrapper with a hard dry-run guard."""
        path = GROWW_ENDPOINTS.get(endpoint_key, "")
        url = f"{GROWW_BASE_URL}{path}{path_suffix}"
        headers = self._post_headers() if method.upper() == "POST" else self._base_headers()

        built = {
            "method": method.upper(),
            "url": url,
            "query": query or {},
            "headers": {k: ("***" if k == "Authorization" else v) for k, v in headers.items()},
            "body": body,
        }

        if not (self.allow_live and self.creds.access_token):
            return {
                "ok": True,
                "live": False,
                "simulated": True,
                "endpoint": endpoint_key,
                "request": built,
                "message": "Dry-run: request built but not sent.",
                "ref_id": f"sim_{uuid.uuid4().hex[:10]}",
            }

        try:
            import requests  # local import: only needed for the live path
        except Exception:
            return {
                "ok": False,
                "live": True,
                "endpoint": endpoint_key,
                "request": built,
                "message": "Live mode requested but 'requests' library is not installed.",
            }

        try:
            resp = requests.request(
                method.upper(), url, params=query, json=body,
                headers=headers, timeout=self.timeout_sec,
            )
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}
            err = data.get("error") if isinstance(data, dict) else None
            return {
                "ok": resp.ok and (data.get("status") != "FAILURE" if isinstance(data, dict) else True),
                "live": True,
                "endpoint": endpoint_key,
                "status_code": resp.status_code,
                "data": data,
                "message": err.get("message") if isinstance(err, dict) else "OK",
            }
        except Exception as exc:  # network / timeout
            return {
                "ok": False,
                "live": True,
                "endpoint": endpoint_key,
                "request": built,
                "message": f"Request error: {exc}",
            }

    # -- Auth ------------------------------------------------------------

    def mint_access_token(self, key_type: str = "approval", totp: str = "") -> Dict:
        """Generate an access token from API key + secret (approval) or TOTP.

        Token generation uses the API KEY as the Bearer, not the access token.
        Only performs a network call in live mode.
        """
        ts = str(int(time.time()))
        if key_type == "totp":
            body = {"key_type": "totp", "totp": totp}
        else:
            body = {
                "key_type": "approval",
                "checksum": generate_checksum(self.creds.api_secret, ts),
                "timestamp": ts,
            }
        url = f"{GROWW_BASE_URL}{GROWW_ENDPOINTS['token']}"
        built = {"method": "POST", "url": url, "body": body}
        if not (self.allow_live and self.creds.api_key):
            return {"ok": True, "live": False, "simulated": True, "request": built,
                    "message": "Dry-run: token request built but not sent."}
        try:
            import requests
            resp = requests.post(
                url, json=body,
                headers={"Authorization": f"Bearer {self.creds.api_key}",
                         "Content-Type": "application/json"},
                timeout=self.timeout_sec,
            )
            data = resp.json()
            token = data.get("token") or data.get("payload", {}).get("token")
            if token:
                self.creds.access_token = token
            return {"ok": resp.ok, "live": True, "status_code": resp.status_code, "data": data}
        except Exception as exc:
            return {"ok": False, "live": True, "message": f"Token error: {exc}"}

    def validate_session(self) -> Dict:
        if not self.creds.is_ready():
            return {"ok": False, "message": "Groww credentials missing (need access token or key+secret)."}
        # Lightweight validation: fetch user margin.
        return self._request("GET", "user_margin")

    # -- Field mapping helpers ------------------------------------------

    def _leg_to_order(self, leg: Dict, order_reference_id: str) -> Dict:
        """Map a strategy leg to a Groww /v1/order/create body."""
        return {
            "trading_symbol": leg.get("trading_symbol") or leg.get("symbol", ""),
            "quantity": int(leg.get("qty_units") or leg.get("quantity") or 0),
            "price": float(leg.get("price", 0) or 0),
            "trigger_price": float(leg.get("trigger_price", 0) or 0),
            "validity": leg.get("validity", "DAY"),
            "exchange": leg.get("exchange", self.exchange),
            "segment": leg.get("segment", self.segment),
            "product": leg.get("product", "NRML"),
            "order_type": leg.get("order_type", "MARKET"),
            "transaction_type": leg.get("action") or leg.get("transaction_type", "BUY"),
            "order_reference_id": order_reference_id,
        }

    def _margin_leg(self, leg: Dict) -> Dict:
        return {
            "trading_symbol": leg.get("trading_symbol") or leg.get("symbol", ""),
            "transaction_type": leg.get("action") or leg.get("transaction_type", "BUY"),
            "quantity": int(leg.get("qty_units") or leg.get("quantity") or 0),
            "price": float(leg.get("price", 0) or 0),
            "order_type": leg.get("order_type", "MARKET"),
            "product": leg.get("product", "NRML"),
            "exchange": leg.get("exchange", self.exchange),
        }

    # -- Public transport actions ---------------------------------------

    def fetch_basket_margin(self, basket_payload: Dict) -> Dict:
        legs = basket_payload.get("basketOrders") or basket_payload.get("legs") or []
        body = [self._margin_leg(l) for l in legs]
        return self._request("POST", "basket_margin", query={"segment": self.segment}, body=body)

    def place_basket(self, basket_payload: Dict) -> Dict:
        """Place each leg individually (Groww has no multi-leg placement API)."""
        legs = basket_payload.get("basketOrders") or basket_payload.get("legs") or []
        ref_base = f"algo-{uuid.uuid4().hex[:10]}"
        results = []
        for idx, leg in enumerate(legs):
            ref_id = f"{ref_base}-{idx}"
            body = self._leg_to_order(leg, ref_id)
            results.append(self._request("POST", "order_create", body=body))
        ok = all(r.get("ok") for r in results) if results else False
        return {
            "ok": ok,
            "live": bool(self.allow_live and self.creds.access_token),
            "leg_count": len(results),
            "legs": results,
            "message": "All legs submitted." if ok else "One or more legs failed / dry-run.",
        }

    def order_status(self, groww_order_id: str) -> Dict:
        if not groww_order_id:
            return {"ok": False, "message": "Missing groww_order_id."}
        return self._request(
            "GET", "order_status", path_suffix=f"/{groww_order_id}",
            query={"segment": self.segment},
        )

    def get_ltp(self, exchange_symbols, segment: str = "FNO") -> Dict:
        """Fetch last-traded prices for one or more instruments.

        ``exchange_symbols`` is a list like ["NSE_NIFTY25APR24100PE", ...] (max 50).
        Returns {ok, ltps: {exchange_symbol: price}, transport}. In dry-run (no
        live transport) returns ok=False so callers can fall back to other sources.
        """
        syms = [s for s in (exchange_symbols or []) if s]
        if not syms:
            return {"ok": False, "ltps": {}, "message": "No instruments supplied."}
        res = self._request(
            "GET", "ltp", query={"segment": segment, "exchange_symbols": ",".join(syms[:50])},
        )
        ltps: Dict[str, float] = {}
        data = res.get("data") if isinstance(res, dict) else None
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict):
            for k, v in payload.items():
                try:
                    ltps[k] = float(v)
                except (TypeError, ValueError):
                    continue
        return {
            "ok": bool(res.get("ok")) and bool(ltps),
            "ltps": ltps,
            "live": res.get("live", False),
            "message": res.get("message", ""),
            "transport": res,
        }

    def cancel_order(self, groww_order_id: str) -> Dict:
        body = {"segment": self.segment, "groww_order_id": groww_order_id}
        return self._request("POST", "order_cancel", body=body)

    def square_off(self, symbol: str, strategy: str = "") -> Dict:
        """Square-off is not a native Groww endpoint.

        A real implementation must fetch open positions and place reverse MARKET
        orders. Left as a guarded scaffold to avoid unintended market actions.
        """
        return {
            "ok": True,
            "live": False,
            "message": ("Square-off scaffold: fetch open positions and place "
                        "reverse MARKET orders. Not auto-executed for safety."),
            "symbol": symbol,
            "strategy": strategy,
        }


def build_transport(api_key: str, api_secret: str, access_token: str,
                    allow_live: bool = False) -> GrowwTransport:
    return GrowwTransport(
        creds=GrowwCredentials(api_key=api_key, api_secret=api_secret, access_token=access_token),
        allow_live=allow_live,
    )
