"""
src/token_manager.py
====================
Access-token (re)generation for the Auto Algo Trader.

Brokers like Groww issue short-lived daily access tokens. This module mints a
fresh token from the stored API key + secret (approval flow) or TOTP, then
writes it back into ``algo_trade_config.json`` so the runner keeps trading.

Real network calls happen only when ``allow_live=True``.
"""

from __future__ import annotations

import logging
from typing import Dict

from src.algo_trade_config import (
    load_algo_config,
    save_algo_config,
    resolve_broker_creds,
)
from src.live_broker_adapter import get_live_broker_adapter, append_journal_event

logger = logging.getLogger("token_manager")


def regenerate_token(broker: str = "", allow_live: bool = False, cfg: Dict | None = None) -> Dict:
    """Mint a fresh access token and persist it into the config file.

    Returns {ok, has_token, token (masked), message}.
    """
    cfg = cfg or load_algo_config()
    broker = broker or cfg.get("active_broker", "Groww")
    creds = resolve_broker_creds(cfg, broker)

    if not (creds["api_key"] and creds["api_secret"]):
        return {"ok": False, "has_token": False,
                "message": f"{broker}: API key and secret required to regenerate token."}

    if broker != "Groww":
        return {"ok": False, "has_token": False,
                "message": f"Token regeneration is implemented for Groww only (got {broker})."}

    adapter = get_live_broker_adapter(
        broker,
        api_key=creds["api_key"],
        api_secret=creds["api_secret"],
        allow_live=bool(allow_live),
    )
    res = adapter.mint_access_token(
        key_type=creds.get("auth_flow", "approval"),
        totp=creds.get("totp", ""),
        allow_live=bool(allow_live),
    )

    new_token = getattr(adapter, "_access_token", "") or ""
    if res.get("ok") and new_token:
        cfg.setdefault("brokers", {}).setdefault(broker, {})["access_token"] = new_token
        save_algo_config(cfg)
        message = f"{broker}: access token regenerated and saved."
    elif res.get("ok"):
        message = res.get("message", "Token request built (dry-run; no live call).")
    else:
        message = res.get("message", "Token regeneration failed.")

    append_journal_event({
        "event": "token_regenerated",
        "broker": broker,
        "allow_live": bool(allow_live),
        "ok": bool(res.get("ok")),
        "has_token": bool(new_token),
        "message": message,
    })

    return {
        "ok": bool(res.get("ok")),
        "has_token": bool(new_token),
        "token": (new_token[:4] + "…" + new_token[-2:]) if new_token else "",
        "message": message,
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Regenerate broker access token")
    ap.add_argument("--broker", default="", help="Broker name (default: active_broker in config)")
    ap.add_argument("--live", action="store_true", help="Perform a real token call (writes token to config)")
    args = ap.parse_args()

    out = regenerate_token(broker=args.broker, allow_live=args.live)
    print(out["message"])
    if out.get("token"):
        print("Token:", out["token"])
