"""
app.py — Indian Market Study Tool (Streamlit Application)
==========================================================

Entry point for the educational trading analysis application.

How to run
----------
    cd c:\\apps\\ai_prompt_agent
    streamlit run app.py

Structure
---------
• Sidebar     : Global controls (symbol, date range, disclaimer)
• Tab 1       : Institutional Trader View
• Tab 2       : Options Trader View
• Tab 3       : Backtesting Lab
• Tab 4       : Learn / Help

⚠️  DISCLAIMER — READ CAREFULLY
================================
This application is for EDUCATIONAL AND STUDY PURPOSES ONLY.

• It does NOT connect to any broker or exchange.
• It does NOT place, simulate, or recommend real trades.
• All data is SYNTHETIC and does NOT represent actual NSE/BSE prices.
• All analysis is HYPOTHETICAL and NOT financial advice.
• Past backtest performance is NOT predictive of future real-world results.
• Options and futures trading involves significant financial risk, including
  the potential loss of all invested capital.
• Always consult a SEBI-registered financial advisor before making any
  investment decision.
"""

import traceback
import os
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import yaml

from src.backtesting import BacktestEngine
from src.data_provider import DataProvider
from src.final_trade_decision import institutional_trade, option_seller_trade
from src.institutional_view import InstitutionalAnalyzer
from src.option_buyer_strategies import (
    assess_buyer_regime,
    generate_buyer_strategies,
    generate_hedging_strategies)
from src.options_view import STRATEGY_CATALOGUE, OptionsAnalyzer
from src.real_data_loader import load_pcr_data, validate_files
from src.strategy_builder import StrategyBuilder
from src.trade_tracker import TradeTracker
from src.utils import format_inr, get_config, pct_str, setup_logging
from src.mf_tracker import (
    POPULAR_FUNDS, ELSS_FUNDS, INDEX_FUNDS, EQUITY_FUNDS,
    load_nav_history, compute_fund_metrics,
    compute_rolling_returns, simulate_sip, compare_with_nifty, search_funds)
from src.market_microstructure import (
    get_oi_heatmap, calculate_iv_rank, analyze_options_flow,
    detect_crowd_bias, find_smart_entry_zones, calculate_realistic_pnl,
    crowd_vs_smart_analysis)
from src.live_broker_adapter import (
    StartAlgoRequest,
    get_live_broker_adapter,
    append_journal_event,
    tail_journal,
    load_live_positions,
    upsert_live_position,
    remove_live_position)
from src.live_auto_runner import (
    LiveAutoTrader,
    load_config as load_auto_config,
    save_config as save_auto_config)
from src.algo_trade_config import (
    load_algo_config,
    save_algo_config,
    resolve_broker_creds,
    build_legs,
    mask_secret,
    SUPPORTED_BROKERS)
from src.algo_auto_trader import AlgoAutoTrader
from src.token_manager import regenerate_token
from src.realtime_data import refresh_realtime
from src.strategy_selector import (
    evaluate_strategies,
    backtest_winrate,
    recommend as recommend_strategy,
    DEFAULT_STRATEGIES,
    STRATEGY_LABELS)

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Indian Market Study Tool",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed")

# ── Mobile-responsive CSS ────────────────────────────────────────────────────
st.markdown("""
<style>
/* Stack Streamlit columns on mobile screens (≤768px) */
@media (max-width: 768px) {
    /* Stack all columns vertically */
    [data-testid="column"] {
        width: 100% !important;
        flex: none !important;
        min-width: 100% !important;
        padding: 0 !important;
    }
    /* Full-width sidebar on mobile */
    [data-testid="stSidebar"] {
        width: 100% !important;
        min-width: 100% !important;
    }
    /* Shrink tab labels to fit small screens */
    [data-testid="stTab"] button {
        font-size: 11px !important;
        padding: 6px 8px !important;
    }
    /* Make metric blocks stack cleanly */
    [data-testid="metric-container"] {
        width: 100% !important;
    }
    /* Prevent charts from overflowing */
    [data-testid="stPlotlyChart"],
    [data-testid="stArrowVegaLiteChart"] {
        overflow-x: auto !important;
    }
    /* Tighten button rows */
    [data-testid="stButton"] button {
        width: 100% !important;
        margin-bottom: 6px;
    }
}
/* Slightly tighter on tablets (769–1024px) */
@media (min-width: 769px) and (max-width: 1024px) {
    [data-testid="column"] {
        min-width: 45% !important;
        flex-wrap: wrap !important;
    }
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Initialisation (cached so it runs only once per session)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Loading configuration and data …")
def init_app():
    """Initialise config, logging, and data provider once per session."""
    cfg    = get_config("config.yaml")
    logger = setup_logging(cfg["logging"]["log_file"], cfg["logging"]["level"])
    dp     = DataProvider(cfg)
    ia     = InstitutionalAnalyzer(cfg)
    oa     = OptionsAnalyzer(cfg)
    be     = BacktestEngine(cfg)
    sb     = StrategyBuilder(cfg)
    tt     = TradeTracker(cfg)
    logger.info("Application initialised successfully.")
    return cfg, logger, dp, ia, oa, be, sb, tt


try:
    cfg, logger, dp, ia, oa, be, sb, tt = init_app()
except Exception as exc:
    st.error(f"Failed to initialise the application: {exc}")
    st.stop()


def save_risk_controls_to_config(config_path: str, risk_controls: dict) -> tuple[bool, str]:
    """Persist risk controls to config.yaml so they survive app restarts."""
    try:
        path = Path(config_path)
        if not path.exists():
            return False, f"Config file not found: {config_path}"

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        if not isinstance(raw, dict):
            return False, "Config format is invalid (expected mapping at root)."

        raw["risk_controls"] = {
            "gap_shock_pct": float(risk_controls["gap_shock_pct"]),
            "base_stop_slippage_pct": float(risk_controls["base_stop_slippage_pct"]),
            "extra_slippage_per_gap_pct": float(risk_controls["extra_slippage_per_gap_pct"]),
            "max_stop_slippage_pct": float(risk_controls["max_stop_slippage_pct"]),
            "trailing_lock_pct": float(risk_controls["trailing_lock_pct"]),
            "trailing_activation_pct_to_target": float(risk_controls["trailing_activation_pct_to_target"]),
            "daily_max_loss_inr": float(risk_controls["daily_max_loss_inr"]),
        }

        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=False)

        return True, "Risk controls saved to config.yaml"
    except Exception as exc:
        return False, f"Could not save config: {exc}"


def _format_price_inr(value: float) -> str:
    """Format a numeric price in INR for broker ticket text."""
    try:
        return f"₹{float(value):,.2f}"
    except Exception:
        return "₹0.00"


def _build_groww_ticket_text(
    *,
    setup_name: str,
    symbol_name: str,
    expiry: str,
    lots: int,
    lot_sz: int,
    entry: float,
    stop_loss: float,
    target: float,
    direction: str,
    legs: list[dict],
    note: str = "") -> str:
    """Create a broker-assist text ticket that can be copied into Groww flow manually."""
    total_units = int(max(1, lots) * max(1, lot_sz))
    lines = [
        "GROWW TRADE TICKET (MANUAL ASSIST)",
        f"Setup: {setup_name}",
        f"Symbol: {symbol_name}",
        f"Expiry: {expiry}",
        f"Direction: {direction.upper()}",
        f"Lots: {lots} | Lot size: {lot_sz} | Total units/leg: {total_units}",
        "",
        "Entry/Exit Plan (strategy level):",
        f"- Entry reference: {_format_price_inr(entry)}",
        f"- Stop-loss trigger: {_format_price_inr(stop_loss)}",
        f"- Target trigger: {_format_price_inr(target)}",
        "",
        "Legs:",
    ]

    for idx, leg in enumerate(legs, start=1):
        lines.append(
            f"{idx}. {leg.get('action', 'BUY')} {leg.get('option_type', '')} "
            f"{leg.get('strike', '')} x {total_units} units"
        )

    lines.extend([
        "",
        "Execution Checklist:",
        "- Use same expiry for all legs.",
        "- Keep quantity equal across all legs.",
        "- Prefer basket order; if unavailable, place hedge legs first.",
        "- Apply SL/Target on net position value (not on one leg).",
    ])

    if note:
        lines.extend(["", f"Notes: {note}"])

    return "\n".join(lines)


def _render_groww_ticket_ui(ticket_text: str, key_prefix: str):
    """Render copy/download controls for a generated Groww manual ticket."""
    st.success("Groww ticket generated. Copy or download it, then place in Groww manually.")
    st.text_area(
        "Groww order ticket",
        value=ticket_text,
        height=280,
        key=f"{key_prefix}_groww_text")
    st.download_button(
        "Download ticket (.txt)",
        data=ticket_text,
        file_name=f"groww_ticket_{key_prefix}.txt",
        mime="text/plain",
        key=f"{key_prefix}_groww_download")
    st.markdown("[Open Groww Options](https://groww.in/options)")
    st.caption("This app does not place live orders. Ticket is for fast manual execution only.")


def _render_copy_button_html(copy_text: str, label: str, key_suffix: str):
        """Render a client-side clipboard button in Streamlit using HTML/JS."""
        _payload = json.dumps(copy_text)
        _btn_id = f"copy_btn_{key_suffix}".replace(" ", "_").replace(":", "_")
        _html = f"""
        <div style=\"padding-top:4px;\">
            <button id=\"{_btn_id}\"
                            style=\"padding:6px 10px;border-radius:8px;border:1px solid #cccccc;background:#f8f8f8;cursor:pointer;\">
                {label}
            </button>
        </div>
        <script>
            const btn = document.getElementById('{_btn_id}');
            if (btn) {{
                btn.addEventListener('click', async () => {{
                    const original = btn.textContent;
                    try {{
                        const textToCopy = {_payload};
                        if (navigator.clipboard && window.isSecureContext) {{
                            await navigator.clipboard.writeText(textToCopy);
                        }} else {{
                            const ta = document.createElement('textarea');
                            ta.value = textToCopy;
                            ta.style.position = 'fixed';
                            ta.style.left = '-9999px';
                            ta.style.top = '0';
                            document.body.appendChild(ta);
                            ta.focus();
                            ta.select();
                            const ok = document.execCommand('copy');
                            document.body.removeChild(ta);
                            if (!ok) {{
                                throw new Error('execCommand copy failed');
                            }}
                        }}
                        btn.textContent = 'Copied';
                        btn.style.background = '#e7f7ec';
                        setTimeout(() => {{
                            btn.textContent = original;
                            btn.style.background = '#f8f8f8';
                        }}, 1400);
                    }} catch (e) {{
                        btn.textContent = 'Copy failed';
                        btn.style.background = '#fdecec';
                        setTimeout(() => {{
                            btn.textContent = original;
                            btn.style.background = '#f8f8f8';
                        }}, 1600);
                    }}
                }});
            }}
        </script>
        """
        components.html(_html, height=54, scrolling=False)


def _build_groww_guide_from_trade(trade: dict) -> str:
        """Build a step-by-step Groww execution guide for a logged auto-trade."""
        import re

        symbol_name = str(trade.get("symbol", "NIFTY"))
        strategy_name = str(trade.get("strategy_type", "Auto Trade"))
        instrument = str(trade.get("instrument", ""))
        direction = str(trade.get("direction", "buy")).lower()
        strike_text = str(trade.get("strike", ""))
        expiry = str(trade.get("expiry", "")) or "Check broker chain"
        trade_date = str(trade.get("date", ""))
        trade_time = str(trade.get("entry_time", ""))
        qty_lots = int(trade.get("qty_lots", 1) or 1)
        lot_sz = int(trade.get("lot_size", 25) or 25)
        units = qty_lots * lot_sz
        entry = float(trade.get("entry_price", 0) or 0)
        sl = float(trade.get("stop_loss", 0) or 0)
        target = float(trade.get("target", 0) or 0)
        status = str(trade.get("status", "Open"))
        wing_inferred = bool(trade.get("wing_inferred", False))
        wing_method = str(trade.get("wing_inference_method", ""))
        capital_model = _capital_model_label(trade)
        broker_note = _broker_margin_note(trade)

        legs = []
        is_condor_like = "iron condor" in instrument.lower()

        short_ce = trade.get("short_ce_strike")
        short_pe = trade.get("short_pe_strike")
        buy_ce = trade.get("buy_ce_strike")
        buy_pe = trade.get("buy_pe_strike")

        if (not short_ce or not short_pe) and "/" in strike_text:
            for raw in strike_text.split("/"):
                p = raw.strip()
                strike = re.sub(r"[^0-9]", "", p)
                if "CE" in p and not short_ce:
                    short_ce = strike
                if "PE" in p and not short_pe:
                    short_pe = strike

        if is_condor_like:
            # Iron condor must be 4 legs: buy PE wing, sell PE short, sell CE short, buy CE wing.
            legs.append(f"- BUY PE {buy_pe if buy_pe else '[WING_PE_MISSING]'} x {units} units")
            legs.append(f"- SELL PE {short_pe if short_pe else '[SHORT_PE_MISSING]'} x {units} units")
            legs.append(f"- SELL CE {short_ce if short_ce else '[SHORT_CE_MISSING]'} x {units} units")
            legs.append(f"- BUY CE {buy_ce if buy_ce else '[WING_CE_MISSING]'} x {units} units")
        elif "/" in strike_text and ("CE:" in strike_text or "PE:" in strike_text):
            for raw in strike_text.split("/"):
                p = raw.strip()
                opt_type = "CE" if "CE" in p else "PE"
                strike = re.sub(r"[^0-9]", "", p)
                action = "SELL" if "sell" in direction else "BUY"
                legs.append(f"- {action} {opt_type} {strike} x {units} units")
        else:
            opt_type = "CE" if "CE" in instrument.upper() else "PE" if "PE" in instrument.upper() else "OPTION"
            strike = re.sub(r"[^0-9]", "", strike_text) or strike_text
            action = "SELL" if "sell" in direction else "BUY"
            legs.append(f"- {action} {opt_type} {strike} x {units} units")

        notes = []
        if is_condor_like and (not buy_ce or not buy_pe):
            notes.append("Wing strikes missing in this historical row. Open Final Trade Decision for current condor wing strikes before placing live order.")
        if wing_inferred:
            notes.append(f"Wing legs are inferred from historical data ({wing_method or 'heuristic'}). Verify strikes before placing.")
        notes.append(f"Capital model: {capital_model}")
        notes.append(f"Broker margin note: {broker_note}")
        if status != "Open":
                notes.append(f"This trade status is {status}. Use this guide for review/replay, not fresh entry.")

        guide = [
                "GROWW STEP-BY-STEP TRADE GUIDE",
                f"Trade ID: {trade.get('id', 'N/A')}",
                f"Date/Time: {trade_date} {trade_time}",
                f"Strategy: {strategy_name}",
                f"Instrument: {instrument}",
                f"Symbol: {symbol_name}",
                f"Expiry: {expiry}",
                "",
                "1) Open Groww and go to F&O option chain for the symbol.",
                "2) Select the same expiry as this trade.",
                "3) Create basket and add these legs:",
                *legs,
                "4) Keep identical quantity for every leg.",
                f"   - Lots: {qty_lots}",
                f"   - Lot size: {lot_sz}",
                f"   - Total units per leg: {units}",
                "5) Entry plan:",
                f"   - Reference entry value: {_format_price_inr(entry)}",
                "6) Risk/exit plan (net position value):",
                f"   - Stop-loss trigger: {_format_price_inr(sl)}",
                f"   - Target trigger: {_format_price_inr(target)}",
                "7) On SL/Target trigger, exit all legs together as one basket.",
                "8) Verify margin, charges, and freeze limits before final submit.",
                "",
                "Safety:",
                "- This app is educational and does not place live orders automatically.",
                "- Double-check expiry, strike, action, and quantity before placing.",
        ]

        if notes:
                guide.extend(["", "Notes:"])
                guide.extend([f"- {n}" for n in notes])

        return "\n".join(guide)


def _capital_model_label(trade: dict) -> str:
    """Describe how Invested ₹ is calculated for the given trade row."""
    instrument = str(trade.get("instrument", "")).lower()
    margin_type = str(trade.get("margin_type", "")).lower()
    direction = str(trade.get("direction", "")).lower()

    if "iron condor" in instrument:
        return "Proxy (spread-width x lot; educational)"
    if "spread" in instrument:
        return "Proxy (defined-risk spread estimate)"
    if margin_type == "premium" or "buy" in direction:
        return "Premium paid (entry x lot x qty)"
    if margin_type == "span" or "sell" in direction:
        return "Proxy SPAN estimate (educational)"
    return "Educational proxy"


def _broker_margin_note(trade: dict) -> str:
    """Explain broker-side margin caveat so users don't treat app proxy as exchange margin."""
    lot_size = int(trade.get("lot_size", 0) or 0)
    instrument = str(trade.get("instrument", "")).lower()
    wing_source = (
        "Inferred" if bool(trade.get("wing_inferred", False))
        else ("Exact" if all([
            trade.get("short_ce_strike"), trade.get("short_pe_strike"),
            trade.get("buy_ce_strike"), trade.get("buy_pe_strike")
        ]) else "Missing")
    ) if "iron condor" in instrument else "N/A"

    base = "Broker/exchange margin can differ materially; verify in Groww before order."
    lot_msg = f" App lot size={lot_size}."
    if "iron condor" in instrument:
        return f"{base}{lot_msg} Wing source={wing_source}."
    return f"{base}{lot_msg}"

# Initialise session state keys
if "real_data_loaded" not in st.session_state:
    st.session_state["real_data_loaded"] = False

# ---------------------------------------------------------------------------
# Sidebar — global controls and disclaimer
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📈 Indian Market Study Tool")
    st.caption("For educational study only · Not financial advice")
    st.divider()

    # ---- Instrument type + symbol ----
    all_syms  = dp.get_all_symbols()
    inst_type = st.radio("Instrument Type", ["Index", "Stock"], horizontal=True)

    if inst_type == "Index":
        sym_choices = all_syms["indices"]
    else:
        sym_choices = all_syms["stocks"]
        if not sym_choices:
            st.warning("No stocks configured. Add stocks to config.yaml → symbols.stocks")
            sym_choices = all_syms["indices"]

    symbol = st.selectbox(
        "Symbol",
        options=sym_choices,
        index=0,
        help="Select an index or stock. Synthetic data is auto-generated if no real file is loaded.")

    # Ensure synthetic data exists for the chosen symbol (on-demand for stocks)
    dp.ensure_symbol_data(symbol)

    lot_size = cfg["data"]["lot_sizes"].get(symbol, 1)
    tick     = cfg["data"]["tick_sizes"].get(symbol, 50)
    st.caption(f"Lot size: **{lot_size}** units | Strike tick: **{tick}**")

    capital_budget = st.number_input(
        "Capital Budget (₹)",
        min_value=25_000,
        max_value=500_000,
        value=150_000,
        step=25_000,
        help=(
            "Max capital (margin or premium) you want to deploy per trade. "
            "Recommended lot quantity is auto-calculated to stay within this limit."
        ))
    st.caption(f"Budget: **₹{capital_budget:,.0f}** — lots auto-sized to fit")

    # When real data is active use its own date boundaries so the filter never returns empty
    if st.session_state.get("real_data_loaded") and dp._real_futures is not None:
        _rmin = dp._real_futures["date"].min().date()
        _rmax = dp._real_futures["date"].max().date()
        _default = (_rmin, _rmax)
        _note    = f"📅 Auto-set to real data period ({_rmin} → {_rmax})"
    else:
        _default = (pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-12-31").date())
        _note    = None

    date_range = st.date_input(
        "Date Range",
        value=_default,
        min_value=pd.Timestamp("2023-01-01"),
        max_value=pd.Timestamp("2026-12-31"),
        help="Select the historical period to analyse.")
    if _note:
        st.caption(_note)
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = str(date_range[0]), str(date_range[1])
    else:
        start_date = str(_default[0])
        end_date   = str(_default[1])

    # ---- Live risk controls (paper-trade only) ----
    st.divider()
    st.subheader("🛡️ Risk Controls")
    st.caption("Adjust paper-trade protection rules for gap shocks and drawdown limits.")

    rc_cfg = cfg.get("risk_controls", {})
    rc_live = tt.get_risk_controls()
    rc_default = {
        "gap_shock_pct": float(rc_cfg.get("gap_shock_pct", rc_live.get("gap_shock_pct", 1.2))),
        "base_stop_slippage_pct": float(rc_cfg.get("base_stop_slippage_pct", rc_live.get("base_stop_slippage_pct", 0.2))),
        "extra_slippage_per_gap_pct": float(rc_cfg.get("extra_slippage_per_gap_pct", rc_live.get("extra_slippage_per_gap_pct", 0.25))),
        "max_stop_slippage_pct": float(rc_cfg.get("max_stop_slippage_pct", rc_live.get("max_stop_slippage_pct", 3.0))),
        "trailing_lock_pct": float(rc_cfg.get("trailing_lock_pct", rc_live.get("trailing_lock_pct", 0.35))),
        "trailing_activation_pct_to_target": float(rc_cfg.get("trailing_activation_pct_to_target", rc_live.get("trailing_activation_pct_to_target", 40.0))),
        "daily_max_loss_inr": float(rc_cfg.get("daily_max_loss_inr", rc_live.get("daily_max_loss_inr", -15000.0))),
    }

    with st.expander("Configure risk guardrails", expanded=False):
        c1, c2 = st.columns(2)
        gap_shock_pct = c1.number_input(
            "Gap shock threshold (%)",
            min_value=0.1,
            max_value=10.0,
            value=float(rc_live.get("gap_shock_pct", rc_default["gap_shock_pct"])),
            step=0.1)
        base_stop_slippage_pct = c2.number_input(
            "Base stop slippage (%)",
            min_value=0.0,
            max_value=5.0,
            value=float(rc_live.get("base_stop_slippage_pct", rc_default["base_stop_slippage_pct"])),
            step=0.05)
        extra_slippage_per_gap_pct = c1.number_input(
            "Extra slippage per gap (%)",
            min_value=0.0,
            max_value=5.0,
            value=float(rc_live.get("extra_slippage_per_gap_pct", rc_default["extra_slippage_per_gap_pct"])),
            step=0.05)
        max_stop_slippage_pct = c2.number_input(
            "Max stop slippage cap (%)",
            min_value=0.1,
            max_value=10.0,
            value=float(rc_live.get("max_stop_slippage_pct", rc_default["max_stop_slippage_pct"])),
            step=0.1)
        trailing_lock_pct = c1.number_input(
            "Trailing lock fraction (0-1)",
            min_value=0.0,
            max_value=1.0,
            value=float(rc_live.get("trailing_lock_pct", rc_default["trailing_lock_pct"])),
            step=0.05)
        trailing_activation_pct_to_target = c2.number_input(
            "Trailing activation (% to target)",
            min_value=1.0,
            max_value=100.0,
            value=float(rc_live.get("trailing_activation_pct_to_target", rc_default["trailing_activation_pct_to_target"])),
            step=1.0)
        daily_max_loss_inr = st.number_input(
            "Daily max loss (INR, negative)",
            min_value=-1_000_000.0,
            max_value=-100.0,
            value=float(rc_live.get("daily_max_loss_inr", rc_default["daily_max_loss_inr"])),
            step=100.0)

        current_rc = {
            "gap_shock_pct": gap_shock_pct,
            "base_stop_slippage_pct": base_stop_slippage_pct,
            "extra_slippage_per_gap_pct": extra_slippage_per_gap_pct,
            "max_stop_slippage_pct": max_stop_slippage_pct,
            "trailing_lock_pct": trailing_lock_pct,
            "trailing_activation_pct_to_target": trailing_activation_pct_to_target,
            "daily_max_loss_inr": daily_max_loss_inr,
        }

        ap1, ap2, ap3 = st.columns(3)
        if ap1.button("Apply risk controls", width='stretch'):
            tt.set_risk_controls(current_rc)
            st.success("Risk controls applied for this session.")

        if ap2.button("Reset to config defaults", width='stretch'):
            tt.set_risk_controls(rc_default)
            st.success("Risk controls reset to config defaults.")

        if ap3.button("Save as defaults", width='stretch'):
            tt.set_risk_controls(current_rc)
            ok, msg = save_risk_controls_to_config("config.yaml", current_rc)
            if ok:
                cfg["risk_controls"] = current_rc
                st.success(msg)
            else:
                st.error(msg)

        st.caption("Apply affects current session. Save as defaults persists values to config.yaml.")

    # Compact always-visible snapshot of currently active risk controls
    rc_now = tt.get_risk_controls()
    risk_profile = "Balanced"
    profile_renderer = st.warning
    if (
        rc_now["gap_shock_pct"] <= 1.0
        and rc_now["max_stop_slippage_pct"] <= 2.0
        and rc_now["daily_max_loss_inr"] >= -10000
    ):
        risk_profile = "Strict"
        profile_renderer = st.success
    elif (
        rc_now["gap_shock_pct"] >= 2.5
        or rc_now["max_stop_slippage_pct"] >= 5.0
        or rc_now["daily_max_loss_inr"] <= -50000
    ):
        risk_profile = "Loose"
        profile_renderer = st.error

    profile_renderer(
        "\n".join([
            f"**Active Risk Profile: {risk_profile}**",
            f"Gap shock: {rc_now['gap_shock_pct']:.2f}%",
            (
                "Stop slippage: "
                f"base {rc_now['base_stop_slippage_pct']:.2f}% + "
                f"{rc_now['extra_slippage_per_gap_pct']:.2f}%/gap "
                f"(cap {rc_now['max_stop_slippage_pct']:.2f}%)"
            ),
            (
                "Trailing: "
                f"lock {rc_now['trailing_lock_pct']:.2f} after "
                f"{rc_now['trailing_activation_pct_to_target']:.0f}% target progress"
            ),
            f"Daily kill-switch: ₹{rc_now['daily_max_loss_inr']:,.0f}",
        ])
    )

    st.divider()
    st.warning(
        "⚠️ **DISCLAIMER**\n\n"
        "This tool is for **educational study only**.\n"
        "- No real trades are placed.\n"
        "- All data is **synthetic / fictional**.\n"
        "- Nothing here is financial advice.\n"
        "- Options & futures carry **unlimited loss risk**."
    )

    # ---- Real data toggle ----
    st.divider()
    st.subheader("📂 Real Data (Optional)")
    use_real = st.toggle(
        "Use your downloaded NSE files",
        value=False,
        help="Switch from synthetic sample data to your actual downloaded files.")

    _dl = Path(__file__).parent / "downloads"
    DEFAULT_FUTURES = str(_dl / "app_historical_NIFTY.csv")
    DEFAULT_CHAIN   = str(_dl / "app_option_chain_NIFTY.csv")
    DEFAULT_PCR     = str(_dl / "app_pcr_NIFTY.csv")

    if use_real:
        futures_file = st.text_input("NIFTY 50 History CSV",  value=DEFAULT_FUTURES, key="real_futures")
        chain_file   = st.text_input("Option Chain CSV",      value=DEFAULT_CHAIN,   key="real_chain")
        pcr_file     = st.text_input("PCR CSV",               value=DEFAULT_PCR,     key="real_pcr")

        # Validate files
        val = validate_files(futures_file, chain_file, pcr_file)
        for msg in val["messages"]:
            st.caption(msg)

        if val["all_ok"]:
            if st.button("Load Real Data", type="primary", width='stretch'):
                try:
                    info = dp.load_real_data(futures_file, chain_file, pcr_file, symbol=symbol)
                    st.session_state["real_data_loaded"]  = True
                    st.session_state["real_data_symbol"]  = symbol
                    st.session_state["real_data_info"]    = info
                    st.session_state["real_pcr_path"]     = pcr_file
                    st.success(
                        f"✅ Real data loaded!\n"
                        f"- Symbol:        {info.get('symbol', symbol)}\n"
                        f"- Price history: {info['futures_rows']} days\n"
                        f"- Option chain:  {info['chain_rows']} strikes  "
                        f"(expiry {info['chain_date']}, spot ₹{info['spot']:,.2f})\n"
                        f"- PCR records:   {info['pcr_rows']} days"
                    )
                except Exception as exc:
                    st.error(f"Failed to load real data: {exc}")
        else:
            st.info("Fix missing files above then click Load.")
    else:
        # Clear real data when toggle is off
        if st.session_state.get("real_data_loaded"):
            dp.clear_real_data()
            st.session_state["real_data_loaded"] = False

    # Show loaded status badge
    if st.session_state.get("real_data_loaded"):
        info = st.session_state.get("real_data_info", {})
        st.success(
            f"**Live data active ({info.get('symbol', 'N/A')})** — "
            f"Spot ₹{info.get('spot', 0):,.2f} | "
            f"Expiry {info.get('chain_date', 'N/A')}"
        )

    # ---- Last data refresh status (sidebar top - make visible) ----
    st.divider()
   
    # Add refresh button to manually update data
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption("📡 **Real-time Market Data**")
    with col2:
        if st.button("🔄", help="Refresh data from downloads", key="sidebar_refresh"):
            st.rerun()
   
    try:
        import glob as _g, json as _js2
        _oc_list = sorted(
            _g.glob(str(Path(__file__).parent / "downloads" / "option_chain_*.json")),
            key=lambda p: Path(p).stat().st_mtime, reverse=True)
        if _oc_list:
            _d = _js2.loads(Path(_oc_list[0]).read_bytes().decode("utf-8-sig"))
            _cron_t = _d.get("cron_run_time", "") or ""
            _mkt_t  = _d.get("timestamp", "")      or ""
            _spot_v = float(_d.get("spot_price", 0) or 0)
            _vix_v  = float(_d.get("vix", 0) or 0)
            _pcr_v  = float(_d.get("pcr", 0) or 0)
            try:
                from datetime import datetime as _dt2
                _cron_fmt = _dt2.fromisoformat(_cron_t[:19]).strftime("%d-%b %H:%M") if _cron_t else "—"
                _mkt_fmt  = _dt2.fromisoformat(_mkt_t[:19]).strftime("%d-%b %H:%M")  if _mkt_t  else "—"
            except Exception:
                _cron_fmt = _cron_t[:16] or "—"
                _mkt_fmt  = _mkt_t[:16]  or "—"
           
            # Display in a nicer format with better visibility
            st.markdown(f"""
            **Cron run:** `{_cron_fmt}`  
            **Market ts:** `{_mkt_fmt}`
            """)
           
            if _spot_v:
                # Use a formatted info box for market data
                st.info(f"🔹 NIFTY ₹{_spot_v:,.1f} | VIX {_vix_v:.2f} | PCR {_pcr_v:.4f}")
           
            # Show last update time in smaller text
            st.caption(f"Last refreshed: {_mkt_fmt}")
        else:
            st.warning("⚠️ No data yet — run the cron first.")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13, tab14 = st.tabs([
    "🏦 Institutional View",
    "⚙️ Options Trader View",
    "🧪 Backtesting Lab",
    "🧭 Strategy Builder",
    "🛒 Option Buyers & Hedging",
    "🎯 Final Trade Decision",
    "📓 Trade Journal",
    "📚 Learn / Help",
    "🤖 Auto Trade Log",
    "📊 Mutual Fund Tracker",
    "🎰 Market Microstructure",
    "🤖 Logic Optimization Agent",
    "🚀 Live Algo Trade",
    "🤖 Auto Algo Trader",
])

# ============================================================
#  TAB 1 — Institutional Trader View
# ============================================================

with tab1:
    st.header(f"Institutional Trader View — {symbol}")
    st.caption(
        "Mimics the style of analysis a futures desk might run. "
        + ("**Using your real NSE files.** Price action and option chain are live data."
           if st.session_state.get("real_data_loaded") else
           "All data is SYNTHETIC and for study only.")
    )

    try:
        futures_df = dp.get_futures_history(symbol, start_date, end_date)
        pcr_df     = dp.get_pcr(symbol, start_date, end_date)

        # Option chain: last available date in the selected range
        # When real data is active the chain date may be outside the price-history range
        # (e.g. price data ends Jun 25, chain is Jun 30) — include it anyway.
        available_chain_dates = dp.get_available_option_dates(symbol)
        if st.session_state.get("real_data_loaded"):
            valid_dates = available_chain_dates  # show all real chain dates
        else:
            valid_dates = [d for d in available_chain_dates if str(d) <= end_date and str(d) >= start_date]
        chain_date  = st.selectbox(
            "Option Chain Date",
            options=valid_dates[::-1] if valid_dates else ["No data"],
            format_func=str,
            help="Select the date for the option chain snapshot.")
        chain_df = dp.get_option_chain(symbol, str(chain_date)) if valid_dates else pd.DataFrame()

    except Exception as exc:
        st.error(f"Error loading data: {exc}")
        st.stop()

    # ---- Guard: empty data ----
    if futures_df.empty:
        st.error(
            "No price data found for the selected date range.  "
            + ("The real data covers a different period — please reload the page "
               "so the date range auto-adjusts."
               if st.session_state.get("real_data_loaded")
               else "Try widening the date range.")
        )
        st.stop()

    # ---- Run analytics ----
    with st.spinner("Running institutional analysis …"):
        enriched    = ia.compute_moving_averages(futures_df)
        enriched    = ia.compute_atr(enriched)
        enriched    = ia.compute_volume_oi_analysis(enriched)
        sentiment   = ia.generate_sentiment(futures_df, chain_df, pcr_df)

    last_row = enriched.iloc[-1]
    spot     = float(last_row["close"])

    # ---- Sentiment banner ----
    score = sentiment.get("score", 0)
    label = sentiment.get("label", "Neutral")
    colour = {"Strongly Bullish": "green", "Moderately Bullish": "green",
               "Neutral / Sideways": "orange", "Moderately Bearish": "red",
               "Strongly Bearish": "red"}.get(label, "orange")

    col_score, col_price, col_atr, col_pcr = st.columns(4)
    col_score.metric("Market Sentiment", label, delta=f"Score: {score}/7",
                     help="Overall market signal (−7=Strongly Bearish to +7=Strongly Bullish). Aggregates SMA position, OI signal, PCR, and Max Pain.")
    col_price.metric("Last Close", f"₹{spot:,.2f}",
                     delta=pct_str(float(last_row.get("price_change", 0))),
                     help="Most recent closing price of the index.")
    col_atr.metric("ATR (14)", f"₹{last_row.get('atr_14', 0):,.2f}",
                   help="Average True Range over 14 days — measures daily volatility in ₹. Used to set SL/Target levels (1.5×ATR = SL, 2×ATR = Target).")
    if sentiment.get("pcr_5d_avg"):
        col_pcr.metric("PCR (5d Avg)", f"{sentiment['pcr_5d_avg']:.3f}",
                       help="Put-Call Ratio 5-day average. >1.25 = bearish market (contrarian bullish). <0.75 = bullish market (contrarian bearish).")

    st.divider()

    # ---- Futures charts ----
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Futures Price & Moving Averages")
        fig_price = go.Figure()
        fig_price.add_trace(go.Candlestick(
            x=enriched["date"], open=enriched["open"], high=enriched["high"],
            low=enriched["low"], close=enriched["close"], name="Price"))
        for ma, colour_ma in [(20, "blue"), (50, "orange"), (200, "red")]:
            col_name = f"sma_{ma}"
            if col_name in enriched.columns:
                fig_price.add_trace(go.Scatter(
                    x=enriched["date"], y=enriched[col_name],
                    name=f"{ma}-day SMA", line=dict(color=colour_ma, width=1.5)))
        fig_price.update_layout(
            height=400, xaxis_rangeslider_visible=False,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig_price, width='stretch')

        # Volume chart
        st.subheader("Volume & Open Interest")
        fig_vol = go.Figure()
        fig_vol.add_trace(go.Bar(
            x=enriched["date"], y=enriched["volume"], name="Volume",
            marker_color="steelblue", opacity=0.6))
        fig_vol.add_trace(go.Scatter(
            x=enriched["date"], y=enriched["oi"], name="Open Interest",
            line=dict(color="darkorange", width=2), yaxis="y2"))
        fig_vol.update_layout(
            height=300,
            yaxis2=dict(overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h"),
            margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_vol, width='stretch')

    with col_right:
        # PCR chart — daily series (or intraday if only one day of real data)
        st.subheader("Put-Call Ratio (PCR)")

        if st.session_state.get("real_data_loaded") and len(pcr_df) <= 3:
            # Real PCR file is intraday (single day) — show intraday view
            try:
                intraday_pcr = pd.read_csv(
                    st.session_state.get("real_pcr_path",
                        r"C:\Users\vishalganesh.s\Downloads\nifty 50_OptionsPcrData.csv"))
                intraday_pcr["datetime"] = (
                    pd.to_datetime(intraday_pcr["CREATED-AT"]).dt.normalize().astype(str)
                    + " " + intraday_pcr["TIME"]
                )
                st.caption(
                    f"ℹ️ Real PCR file covers {intraday_pcr['CREATED-AT'].str[:10].unique()[0]} "
                    "(intraday view). Option-chain derived PCR shown below."
                )
                fig_pcr = go.Figure()
                fig_pcr.add_trace(go.Scatter(
                    x=intraday_pcr["datetime"], y=intraday_pcr["PCR"],
                    name="PCR (intraday)", line=dict(color="purple", width=1.5)))
                fig_pcr.add_hline(y=1.25, line_dash="dash", line_color="red",   annotation_text="1.25")
                fig_pcr.add_hline(y=0.75, line_dash="dash", line_color="green", annotation_text="0.75")
                fig_pcr.update_layout(
                    xaxis_title="Time", yaxis_title="PCR",
                    height=200, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_pcr, width='stretch')
            except Exception:
                pass

            # Show option-chain-derived PCR for today
            if not chain_df.empty:
                total_ce = int(chain_df["CE_OI"].sum())
                total_pe = int(chain_df["PE_OI"].sum())
                oc_pcr   = round(total_pe / total_ce, 3) if total_ce else 0
                st.metric("Option Chain PCR (today)", f"{oc_pcr:.3f}",
                          help="Derived from total PE OI / CE OI in today's real chain.")
        else:
            # Daily PCR series (synthetic or multi-day real)
            fig_pcr = go.Figure()
            fig_pcr.add_trace(go.Scatter(
                x=pcr_df["date"], y=pcr_df["pcr_oi"],
                name="PCR (OI)", line=dict(color="purple", width=2)))
            fig_pcr.add_hline(y=1.25, line_dash="dash", line_color="red",   annotation_text="Bearish 1.25")
            fig_pcr.add_hline(y=0.75, line_dash="dash", line_color="green", annotation_text="Bullish 0.75")
            fig_pcr.add_hline(y=1.0,  line_dash="dot",  line_color="gray")
            fig_pcr.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig_pcr, width='stretch')

        # OI signal table (last 5 days)
        st.subheader("Recent OI/Price Signal")
        signal_table = enriched[["date", "close", "oi_price_signal"]].tail(7).copy()
        signal_table["date"] = signal_table["date"].dt.date
        st.dataframe(signal_table, hide_index=True, width='stretch')

    st.divider()

    # ---- Option Chain ----
    if not chain_df.empty:
        st.subheader(f"Option Chain — {symbol} ({chain_date})")
        spot_chain = float(chain_df["spot"].iloc[0])
        atm_approx = round(spot_chain / cfg["data"]["tick_sizes"].get(symbol, 50)) * cfg["data"]["tick_sizes"].get(symbol, 50)

        def highlight_atm(row):
            if row["strike"] == atm_approx:
                return ["background-color: #ffe0b2"] * len(row)
            elif row["strike"] < atm_approx:
                return ["background-color: #e8f5e9"] * len(row)
            else:
                return ["background-color: #fce4ec"] * len(row)

        display_chain = chain_df[["strike", "CE_OI", "CE_Volume", "CE_IV", "CE_LTP",
                                   "PE_LTP", "PE_IV", "PE_OI", "PE_Volume"]].copy()
        display_chain["strike"] = pd.to_numeric(display_chain["strike"], errors="coerce")
        display_chain = display_chain.dropna(subset=["strike"])
        display_chain["strike"] = display_chain["strike"].astype(int)
        display_chain = display_chain.sort_values("strike", ascending=False)
        st.dataframe(
            display_chain.style.apply(highlight_atm, axis=1),
            hide_index=True, width='stretch', height=400)

        # OI distribution chart
        col_oi1, col_oi2 = st.columns(2)
        with col_oi1:
            st.subheader("OI Distribution by Strike")
            fig_oi = go.Figure()
            fig_oi.add_trace(go.Bar(
                x=chain_df["strike"], y=chain_df["CE_OI"],
                name="Call OI", marker_color="green", opacity=0.7))
            fig_oi.add_trace(go.Bar(
                x=chain_df["strike"], y=chain_df["PE_OI"],
                name="Put OI", marker_color="red", opacity=0.7))
            if sentiment.get("key_levels", {}).get("max_pain"):
                fig_oi.add_vline(
                    x=sentiment["key_levels"]["max_pain"],
                    line_dash="dash", line_color="purple",
                    annotation_text=f"Max Pain ₹{sentiment['key_levels']['max_pain']:,.0f}")
            fig_oi.add_vline(x=spot_chain, line_color="black", line_width=2,
                             annotation_text=f"Spot ₹{spot_chain:,.0f}")
            fig_oi.update_layout(barmode="group", height=350,
                                 margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig_oi, width='stretch')

        with col_oi2:
            st.subheader("IV Smile / Skew")
            fig_iv = go.Figure()
            fig_iv.add_trace(go.Scatter(
                x=chain_df["strike"], y=chain_df["CE_IV"],
                name="Call IV (%)", line=dict(color="green")))
            fig_iv.add_trace(go.Scatter(
                x=chain_df["strike"], y=chain_df["PE_IV"],
                name="Put IV (%)", line=dict(color="red")))
            fig_iv.add_vline(x=spot_chain, line_color="black", line_dash="dot")
            fig_iv.update_layout(height=350, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig_iv, width='stretch')

    st.divider()

    # ---- Institutional View Summary ----
    st.subheader("📋 Institutional-Style Analysis Summary")
    st.caption("Rule-based heuristic analysis — study exercise only, NOT financial advice.")

    col_bull, col_bear = st.columns(2)
    with col_bull:
        st.markdown("**✅ Bullish Signals**")
        for f in sentiment.get("bullish_factors", []):
            st.markdown(f"- {f}")
        if not sentiment.get("bullish_factors"):
            st.markdown("_None identified_")

    with col_bear:
        st.markdown("**❌ Bearish Signals**")
        for f in sentiment.get("bearish_factors", []):
            st.markdown(f"- {f}")
        if not sentiment.get("bearish_factors"):
            st.markdown("_None identified_")

    kl = sentiment.get("key_levels", {})
    if kl:
        st.markdown("**📍 Key Levels**")
        level_data = {
            "Level": ["Current Price", "20-day SMA", "50-day SMA", "200-day SMA",
                      "Max Pain", "Call OI Wall (Resistance)", "Put OI Wall (Support)"],
            "Value (₹)": [
                f"{kl.get('current_price', 0):,.2f}",
                f"{kl.get('sma_20', 0):,.2f}",
                f"{kl.get('sma_50', 0):,.2f}",
                f"{kl.get('sma_200', 0):,.2f}",
                f"{kl.get('max_pain', 0):,.2f}" if kl.get("max_pain") else "N/A",
                f"{kl.get('ce_wall', 0):,.2f}" if kl.get("ce_wall") else "N/A",
                f"{kl.get('pe_wall', 0):,.2f}" if kl.get("pe_wall") else "N/A",
            ],
        }
        st.dataframe(pd.DataFrame(level_data), hide_index=True)

    with st.expander("⚠️ Risk Factors (always read this)"):
        for rf in sentiment.get("risk_factors", []):
            st.markdown(f"- {rf}")


# ============================================================
#  TAB 2 — Options Trader View
# ============================================================

with tab2:
    st.header(f"Options Trader View — {symbol}")
    st.caption("Select a strategy, adjust the strikes, and explore payoff diagrams and Greeks.")

    try:
        futures_df2 = dp.get_futures_history(symbol, start_date, end_date)
        pcr_df2     = dp.get_pcr(symbol, start_date, end_date)

        available_dates2 = dp.get_available_option_dates(symbol)
        if st.session_state.get("real_data_loaded"):
            valid_dates2 = available_dates2  # show all real chain dates
        else:
            valid_dates2 = [d for d in available_dates2 if str(d) <= end_date and str(d) >= start_date]
        chain_date2  = st.selectbox(
            "Option Chain Date",
            options=valid_dates2[::-1] if valid_dates2 else ["No data"],
            format_func=str,
            key="tab2_chain_date")
        chain_df2 = dp.get_option_chain(symbol, str(chain_date2)) if valid_dates2 else pd.DataFrame()
    except Exception as exc:
        st.error(f"Error loading data: {exc}")
        st.stop()

    if chain_df2.empty:
        st.warning("No option chain data available for the selected date/range.")
        st.stop()

    spot2       = float(chain_df2["spot"].iloc[0])
    tick2       = cfg["data"]["tick_sizes"].get(symbol, 50)
    strikes2    = sorted(chain_df2["strike"].unique().tolist())
    atm2        = round(spot2 / tick2) * tick2

    st.caption(f"Spot: **₹{spot2:,.2f}** | ATM Strike: **₹{atm2:,.0f}**")

    col_strat, col_expiry_t = st.columns([2, 1])
    with col_strat:
        strategy_name2 = st.selectbox("Strategy", options=list(STRATEGY_CATALOGUE.keys()))
    with col_expiry_t:
        days_to_expiry = st.number_input("Days to Expiry", min_value=1, max_value=90, value=30)

    T2 = days_to_expiry / 365.0

    cat2 = STRATEGY_CATALOGUE[strategy_name2]
    st.info(f"**{strategy_name2}:** {cat2['description']}")

    # Dynamic strike selectors based on strategy
    strikes_needed = cat2.get("strikes_needed", [])
    strike_values  = {}

    strike_cols = st.columns(min(len(strikes_needed), 4))
    for idx, sk in enumerate(strikes_needed):
        label_map = {
            "strike_buy_ce":   "Buy Call Strike",
            "strike_sell_ce":  "Sell Call Strike",
            "strike_buy_pe":   "Buy Put Strike",
            "strike_sell_pe":  "Sell Put Strike",
            "strike_atm":      "ATM Strike",
            "entry_price":     "Futures Entry Price",
            "strike_pe_wing_buy":  "Buy Put Wing (far OTM)",
            "strike_ce_wing_buy":  "Buy Call Wing (far OTM)",
        }
        label = label_map.get(sk, sk.replace("_", " ").title())

        if sk == "entry_price":
            val = strike_cols[idx % 4].number_input(
                label, value=float(spot2), step=float(tick2), key=f"sk_{sk}")
        elif sk == "strike_pe_wing_buy":
            default_idx = max(0, strikes2.index(atm2) - 8) if atm2 in strikes2 else 0
            val = strike_cols[idx % 4].selectbox(label, strikes2, index=default_idx, key=f"sk_{sk}")
        elif sk == "strike_sell_pe":
            default_idx = max(0, strikes2.index(atm2) - 4) if atm2 in strikes2 else 0
            val = strike_cols[idx % 4].selectbox(label, strikes2, index=default_idx, key=f"sk_{sk}")
        elif sk == "strike_sell_ce":
            atm_idx     = strikes2.index(atm2) if atm2 in strikes2 else len(strikes2) // 2
            default_idx = min(atm_idx + 4, len(strikes2) - 1)
            val = strike_cols[idx % 4].selectbox(label, strikes2, index=default_idx, key=f"sk_{sk}")
        elif sk == "strike_ce_wing_buy":
            atm_idx     = strikes2.index(atm2) if atm2 in strikes2 else len(strikes2) // 2
            default_idx = min(atm_idx + 8, len(strikes2) - 1)
            val = strike_cols[idx % 4].selectbox(label, strikes2, index=default_idx, key=f"sk_{sk}")
        elif sk == "strike_buy_ce":
            atm_idx     = strikes2.index(atm2) if atm2 in strikes2 else len(strikes2) // 2
            val = strike_cols[idx % 4].selectbox(label, strikes2, index=atm_idx, key=f"sk_{sk}")
        elif sk in ("strike_buy_pe", "strike_atm"):
            atm_idx     = strikes2.index(atm2) if atm2 in strikes2 else len(strikes2) // 2
            val = strike_cols[idx % 4].selectbox(label, strikes2, index=atm_idx, key=f"sk_{sk}")
        else:
            atm_idx     = strikes2.index(atm2) if atm2 in strikes2 else len(strikes2) // 2
            val = strike_cols[idx % 4].selectbox(label, strikes2, index=atm_idx, key=f"sk_{sk}")

        strike_values[sk] = val

    # Build legs and compute
    try:
        legs2 = oa.build_legs(strategy_name2, strike_values, chain_df2, T2)
    except Exception as exc:
        st.error(f"Error building strategy legs: {exc}")
        st.stop()

    if not legs2:
        st.warning("Could not build strategy legs. Please check the selected strikes.")
        st.stop()

    # Payoff diagram
    spot_range2 = np.linspace(spot2 * 0.75, spot2 * 1.25, 500)
    pnl2        = oa.compute_payoff(legs2, spot_range2)
    pnl2_inr    = pnl2 * lot_size

    # Risk / reward
    rr_summary = oa.risk_reward_summary(legs2, lot_size, spot2)

    # Greeks
    atm_iv2  = float(chain_df2.loc[(chain_df2["strike"] - spot2).abs().idxmin(), "CE_IV"]) / 100.0
    greeks2  = oa.compute_strategy_greeks(legs2, spot2, T2, sigma=atm_iv2)

    st.divider()
    col_pd, col_info = st.columns([3, 2])

    with col_pd:
        st.subheader("Payoff Diagram at Expiry")
        colours = ["green" if v >= 0 else "red" for v in pnl2_inr]
        fig_pnl = go.Figure()
        fig_pnl.add_trace(go.Scatter(
            x=spot_range2, y=pnl2_inr,
            fill="tozeroy",
            line=dict(color="royalblue", width=2),
            name="P&L (₹)"))
        fig_pnl.add_hline(y=0, line_color="black", line_width=1)
        fig_pnl.add_vline(x=spot2, line_dash="dash", line_color="gray",
                          annotation_text=f"Current ₹{spot2:,.0f}")
        for be_pt in rr_summary.get("breakevens", []):
            fig_pnl.add_vline(
                x=be_pt, line_dash="dot", line_color="orange",
                annotation_text=f"BE ₹{be_pt:,.0f}", annotation_position="top")
        fig_pnl.update_layout(
            xaxis_title="Spot at Expiry (₹)",
            yaxis_title="Profit / Loss (₹ per lot)",
            height=420,
            margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig_pnl, width='stretch')
        st.caption(
            "⚠️ Payoff shown at EXPIRY (intrinsic value only). "
            "Before expiry, the P&L curve would be smoother due to time value."
        )

    with col_info:
        st.subheader("Risk / Reward Summary")
        rr_data = {
            "Metric": [
                "Net Premium (₹/unit)",
                "Max Profit (₹/lot)",
                "Max Loss (₹/lot)",
                "Risk:Reward",
                "Breakeven(s)",
            ],
            "Value": [
                f"₹{rr_summary['net_premium']:,.2f}",
                format_inr(rr_summary['max_profit_inr']),
                format_inr(rr_summary['max_loss_inr']),
                f"1 : {rr_summary['risk_reward_ratio']:.2f}",
                ", ".join([f"₹{b:,.0f}" for b in rr_summary.get("breakevens", [])]) or "N/A",
            ],
        }
        st.dataframe(pd.DataFrame(rr_data), hide_index=True, width='stretch')

        st.subheader("Strategy Greeks")
        agg_g = greeks2["aggregate"]
        greeks_data = {
            "Greek": ["Delta (δ)", "Gamma (Γ)", "Theta (Θ) / day", "Vega (ν) / 1% IV"],
            "Value": [
                f"{agg_g['delta']:+.4f}",
                f"{agg_g['gamma']:+.6f}",
                f"₹{agg_g['theta'] * lot_size:+.2f}",
                f"₹{agg_g['vega']  * lot_size:+.2f}",
            ],
            "Meaning": [
                "₹ gain per ₹1 spot move",
                "Δ change per ₹1 spot move",
                "Daily time decay (₹/lot)",
                "₹ change per 1% IV move",
            ],
        }
        st.dataframe(pd.DataFrame(greeks_data), hide_index=True, width='stretch')

        # Leg-level Greeks
        with st.expander("Per-Leg Greeks"):
            leg_greeks_df = pd.DataFrame(greeks2["legs"])
            st.dataframe(leg_greeks_df, hide_index=True)

    # Strategy explanation
    st.divider()
    st.subheader("📖 Strategy Explanation")
    sentiment2 = ia.generate_sentiment(futures_df2, chain_df2, pcr_df2)
    explanation = oa.get_strategy_explanation(
        strategy_name2,
        sentiment_label=sentiment2.get("label", "Neutral"),
        pcr_5d_avg=sentiment2.get("pcr_5d_avg"),
        atm_iv=atm_iv2 * 100.0)
    st.markdown(explanation)


# ============================================================
#  TAB 3 — Backtesting Lab
# ============================================================

with tab3:
    st.header("Backtesting Lab")
    st.caption(
        "Run historical strategy simulations. "
        "Uses real NIFTY data when loaded via the sidebar toggle."
    )

    # ── Data source notice ────────────────────────────────────
    _bt_real = st.session_state.get("real_data_loaded")
    if _bt_real:
        st.success("📊 **Using real NIFTY data** for backtesting — results reflect actual 1-year price history.")
    else:
        st.info("ℹ️ Using **synthetic data**. Load real NSE files via sidebar for meaningful results.")

    st.warning(
        "⚠️ **Backtesting Limitations:** "
        "Transaction costs and slippage are modelled approximately. "
        "Do NOT interpret these results as evidence that any strategy will be profitable."
    )

    # Strategy selector and parameters
    bt_strategy = st.selectbox(
        "Strategy",
        options=[
            "MA Crossover (Trend Following)",
            "RSI Mean-Reversion",
            "Bollinger Band Breakout",
            "MACD Crossover",
            "PCR Contrarian",
        ],
        key="bt_strategy",
        help="Select a strategy to backtest on 1-year NIFTY data."
    )

    col_p1, col_p2, col_p3 = st.columns(3)

    if bt_strategy == "MA Crossover (Trend Following)":
        short_w = col_p1.number_input("Short MA Window (days)", 5, 50, 20, key="short_w",
                                       help="Fast SMA — reacts quickly to price changes")
        long_w  = col_p2.number_input("Long MA Window  (days)", 20, 200, 50, key="long_w",
                                       help="Slow SMA — defines the major trend")
        bt_lots = col_p3.number_input("Lots", 1, 10, 1, key="bt_lots")
        bt_params_desc = f"Short MA={short_w}, Long MA={long_w}"

    elif bt_strategy == "RSI Mean-Reversion":
        rsi_per  = col_p1.number_input("RSI Period (days)", 5, 30, 14, key="rsi_per",
                                        help="Wilder RSI — 14 is standard")
        oversold = col_p2.number_input("Oversold threshold", 10, 45, 30, key="rsi_os",
                                        help="Buy signal when RSI crosses above this")
        overbought = col_p3.number_input("Overbought threshold", 55, 90, 70, key="rsi_ob",
                                          help="Sell signal when RSI crosses below this")
        bt_lots = 1
        bt_params_desc = f"RSI({rsi_per}), OS={oversold}, OB={overbought}"

    elif bt_strategy == "Bollinger Band Breakout":
        bb_per  = col_p1.number_input("BB Period (days)", 10, 50, 20, key="bb_per",
                                       help="Rolling window for Bollinger Bands")
        bb_std  = col_p2.number_input("Std Dev multiplier", 1.0, 3.0, 2.0, 0.25, key="bb_std",
                                       help="Band width = period SMA ± N × std dev")
        bt_lots = col_p3.number_input("Lots", 1, 10, 1, key="bt_lots")
        bt_params_desc = f"BB({bb_per}, {bb_std}std)"

    elif bt_strategy == "MACD Crossover":
        macd_fast   = col_p1.number_input("Fast EMA", 5, 20, 12, key="macd_fast",
                                           help="Fast EMA period (default 12)")
        macd_slow   = col_p2.number_input("Slow EMA", 15, 50, 26, key="macd_slow",
                                           help="Slow EMA period (default 26)")
        macd_signal = col_p3.number_input("Signal line", 5, 20, 9, key="macd_sig",
                                           help="Signal EMA period (default 9)")
        bt_lots = 1
        bt_params_desc = f"MACD({macd_fast}/{macd_slow}/{macd_signal})"

    else:  # PCR Contrarian
        bull_thr = col_p1.number_input("Bullish PCR (sell signal)", 0.5, 1.0, 0.75, 0.05, key="bull_thr")
        bear_thr = col_p2.number_input("Bearish PCR (buy signal)",  1.0, 2.0, 1.25, 0.05, key="bear_thr")
        pcr_smo  = col_p3.number_input("PCR Smoothing (days)", 1, 20, 5, key="pcr_smo")
        bt_lots  = 1
        bt_params_desc = f"Buy PCR>{bear_thr:.2f}, Sell PCR<{bull_thr:.2f}"

    run_bt = st.button("▶ Run Backtest", type="primary", width='stretch')

    if run_bt:
        with st.spinner("Running backtest …"):
            try:
                futures_bt = dp.get_futures_history(symbol, start_date, end_date)
                pcr_bt     = dp.get_pcr(symbol, start_date, end_date)

                if futures_bt.empty:
                    st.error("No futures data in the selected date range.")
                else:
                    if bt_strategy == "MA Crossover (Trend Following)":
                        result = be.run_ma_crossover(
                            futures_bt, short_window=short_w, long_window=long_w, lot_size=bt_lots)
                    elif bt_strategy == "RSI Mean-Reversion":
                        result = be.run_rsi_strategy(
                            futures_bt, rsi_period=rsi_per,
                            oversold=oversold, overbought=overbought, lot_size=bt_lots)
                    elif bt_strategy == "Bollinger Band Breakout":
                        result = be.run_bollinger_strategy(
                            futures_bt, bb_period=bb_per, num_std=bb_std, lot_size=bt_lots)
                    elif bt_strategy == "MACD Crossover":
                        result = be.run_macd_strategy(
                            futures_bt, fast=macd_fast, slow=macd_slow,
                            signal=macd_signal, lot_size=bt_lots)
                    else:
                        result = be.run_pcr_strategy(
                            futures_bt, pcr_bt,
                            bullish_threshold=bull_thr, bearish_threshold=bear_thr,
                            pcr_smoothing_days=pcr_smo, lot_size=bt_lots)

                    # Compute extended metrics
                    result.metrics = be.compute_extended_metrics(
                        result.equity_curve, result.trades,
                        be.init_capital, risk_free_rate=0.065)

                    st.session_state["bt_result"] = result
                    logger.info(
                        "Backtest run: %s | %s | Symbol=%s | Period=%s to %s",
                        result.strategy_name, bt_params_desc, symbol, start_date, end_date)

            except Exception as exc:
                st.error(f"Backtest failed: {exc}")
                logger.error("Backtest error: %s\n%s", exc, traceback.format_exc())

    # Show results if available
    if "bt_result" in st.session_state:
        result = st.session_state["bt_result"]
        m      = result.metrics

        st.divider()
        st.subheader(f"Results: {result.strategy_name}")

        # Metrics row
        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        col_m1.metric("Total Return", f"{m.get('total_return_pct', 0):.1f}%",
                     help="(Final - Initial) / Initial × 100")
        col_m2.metric("CAGR",         f"{m.get('cagr_pct', 0):.1f}%",
                     help="Compound Annual Growth Rate")
        col_m3.metric("Max Drawdown", f"{m.get('max_drawdown_pct', 0):.1f}%",
                     help="Worst peak-to-trough fall in portfolio value")
        col_m4.metric("Sharpe Ratio", f"{m.get('sharpe_ratio', 0):.2f}",
                     help=">1 = good, >2 = excellent. Excess return / volatility.")
        col_m5.metric("Win Rate",     f"{m.get('win_rate_pct', 0):.1f}%",
                     help="% of closed trades with positive P&L")

        col_m6, col_m7, col_m8, col_m9, col_m10 = st.columns(5)
        col_m6.metric("Total Trades",   m.get("num_trades", 0))
        col_m7.metric("Avg Win",  format_inr(m.get("avg_win_inr",  0)),
                     help="Average profit on winning trades")
        col_m8.metric("Avg Loss", format_inr(m.get("avg_loss_inr", 0)),
                     help="Average loss on losing trades")
        col_m9.metric("Calmar Ratio",  f"{m.get('calmar_ratio', 0):.2f}",
                     help="CAGR / |Max Drawdown|. >0.5 is acceptable, >1 is good.")
        col_m10.metric("Sortino Ratio", f"{m.get('sortino_ratio', 0):.2f}",
                      help="Like Sharpe but only penalises downside volatility.")

        col_m11, col_m12, col_m13 = st.columns(3)
        col_m11.metric("Profit Factor", f"{m.get('profit_factor', 0):.2f}",
                       help="Gross profit / Gross loss. >1.5 is good.")
        col_m12.metric("Avg Trade (days)", m.get("avg_trade_days", 0),
                       help="Average holding period per trade")
        col_m13.metric("Max Losing Streak", m.get("max_losing_streak", 0),
                       help="Consecutive losing trades — tests your patience!")

        st.divider()

        # Equity curve
        col_eq, col_reg = st.columns([3, 2])
        with col_eq:
            st.subheader("Equity Curve")
            eq_df = result.equity_curve.copy()

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=eq_df["date"], y=eq_df["portfolio_value"],
                name="Portfolio Value", line=dict(color="royalblue", width=2),
                fill="tozeroy"))
            # Drawdown overlay
            pv = eq_df["portfolio_value"].values
            peak = np.maximum.accumulate(pv)
            dd   = (pv - peak) / peak * 100

            fig_eq.add_trace(go.Scatter(
                x=eq_df["date"], y=peak,
                name="Peak Value", line=dict(color="gray", dash="dot", width=1)))
            fig_eq.update_layout(
                xaxis_title="Date", yaxis_title="Portfolio Value (₹)",
                height=400, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig_eq, width='stretch')

            # Drawdown chart
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(
                x=eq_df["date"], y=dd,
                fill="tozeroy", line=dict(color="red", width=1),
                name="Drawdown (%)"))
            fig_dd.update_layout(
                xaxis_title="Date", yaxis_title="Drawdown (%)",
                height=200, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_dd, width='stretch')

        with col_reg:
            st.subheader("Performance by Market Regime")
            if result.regime_summary:
                reg_df = pd.DataFrame(result.regime_summary).T.reset_index()
                reg_df.columns = ["Regime", "Days", "Avg Ann. Return (%)", "Volatility (%)"]
                st.dataframe(reg_df, hide_index=True, width='stretch')

                st.markdown("""
**Regime definitions:**
- **Trending Up**   : Price > 50-day MA by >2%
- **Trending Down** : Price < 50-day MA by >2%
- **Sideways**      : Price within ±2% of 50-day MA

Understanding how a strategy behaves across regimes helps identify when
to *use* or *avoid* it in real conditions.
                """)

            # Trade log
            st.subheader("Trade Log")
            if result.trades:
                trade_df = pd.DataFrame([
                    {
                        "Entry Date":  t.entry_date.date() if hasattr(t.entry_date, "date") else t.entry_date,
                        "Exit Date":   t.exit_date.date()  if hasattr(t.exit_date,  "date") else t.exit_date,
                        "Entry ₹":     f"₹{t.entry_price:,.2f}",
                        "Exit ₹":      f"₹{t.exit_price:,.2f}",
                        "P&L ₹":       f"{'+'if t.pnl>=0 else ''}{t.pnl:,.0f}",
                        "Result":      "✅ Win" if t.pnl > 0 else "❌ Loss",
                    }
                    for t in result.trades
                ])
                st.dataframe(trade_df, hide_index=True, width='stretch', height=250)
            else:
                st.info("No completed trades in the selected period / parameters.")

        # Monthly P&L heatmap
        monthly_pnl = m.get("monthly_pnl", {})
        if monthly_pnl and len(monthly_pnl) >= 3:
            st.divider()
            st.subheader("📅 Monthly P&L Heatmap (%)")
            _months_df = pd.DataFrame([
                {"Year": k[:4], "Month": k[5:], "P&L %": v}
                for k, v in monthly_pnl.items()
            ])
            _pivot = _months_df.pivot(index="Year", columns="Month", values="P&L %")
            _month_order = ["01","02","03","04","05","06","07","08","09","10","11","12"]
            _pivot = _pivot.reindex(columns=[m for m in _month_order if m in _pivot.columns])
            _pivot.columns = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][
                :len(_pivot.columns)]

            fig_heat = go.Figure(data=go.Heatmap(
                z=_pivot.values,
                x=list(_pivot.columns),
                y=list(_pivot.index),
                colorscale=[
                    [0.0, "#d32f2f"], [0.45, "#ffcdd2"],
                    [0.5, "#f5f5f5"],
                    [0.55, "#c8e6c9"], [1.0, "#1b5e20"],
                ],
                zmid=0,
                text=[[f"{v:+.1f}%" if not pd.isna(v) else "" for v in row]
                      for row in _pivot.values],
                texttemplate="%{text}",
                hovertemplate="Month: %{x}<br>Year: %{y}<br>P&L: %{z:+.1f}%<extra></extra>",
                showscale=True))
            fig_heat.update_layout(
                height=max(150, len(_pivot) * 50 + 60),
                margin=dict(l=10, r=10, t=30, b=10),
                xaxis_title="Month", yaxis_title="Year")
            st.plotly_chart(fig_heat, width='stretch')
            st.caption("Green = profitable month | Red = losing month | White = breakeven")

        # Educational limitations
        with st.expander("📚 Backtest Limitations (read before drawing conclusions)"):
            st.markdown("""
### Why backtest results can be misleading

1. **Synthetic data**: This app uses randomly generated price data (GBM model).
   Real markets have fat tails, momentum, and mean-reversion that GBM doesn't capture.

2. **Overfitting / curve-fitting**: If you tune the parameters (e.g., MA windows)
   to maximise backtest return, the strategy is likely *overfitted* to the historical
   data and will underperform on new data. Always test on an *out-of-sample* period.

3. **Transaction costs and slippage**: Real costs are often higher than assumed here,
   especially for retail traders (STT, brokerage, impact cost, spread).

4. **Survivorship bias**: We backtest only on NIFTY, which has survived and grown.
   A real portfolio might include instruments that performed far worse.

5. **Execution gaps**: The model assumes fills at next-day open. In reality, gaps
   between close and open can significantly affect results.

6. **Regime change**: A strategy that worked in 2024 may not work in 2025 due to
   changing market structure, liquidity, or participants.

7. **No risk management**: This simple model uses fixed lots and no stop-losses.
   A real strategy would use position sizing and risk controls.

> **Bottom line**: A good backtest is a *necessary but not sufficient* condition
> for a strategy to work in live trading. Use backtests to *understand* a strategy,
> not to *predict* future profits.
            """)


# ============================================================
#  TAB 4 — Strategy Builder
# ============================================================

with tab4:
    st.header("🧭 Strategy Builder")
    st.caption(
        "Rule-based strategy generator for learning. No order placement, no broker connectivity, no financial advice."
    )
    st.warning(
        "⚠️ STUDY-ONLY MODE: These are educational, hypothetical rule-sets. "
        "They are NOT live trade calls and do NOT guarantee outcomes."
    )

    # Reuse the same loaded data pipeline
    try:
        rw_futures = dp.get_futures_history(symbol, start_date, end_date)
        rw_pcr = dp.get_pcr(symbol, start_date, end_date)
        rw_chain_dates = dp.get_available_option_dates(symbol)

        if st.session_state.get("real_data_loaded"):
            rw_valid_dates = rw_chain_dates
        else:
            rw_valid_dates = [d for d in rw_chain_dates if str(d) <= end_date and str(d) >= start_date]

        rw_chain_date = st.selectbox(
            "Strategy Builder Option Chain Date",
            options=rw_valid_dates[::-1] if rw_valid_dates else ["No data"],
            format_func=str,
            key="rw_chain_date",
            help="Choose chain snapshot for strike/premium approximation.")
        rw_chain = dp.get_option_chain(symbol, str(rw_chain_date)) if rw_valid_dates else pd.DataFrame()
    except Exception as exc:
        st.error(f"Error loading strategy builder data: {exc}")
        st.stop()

    if rw_futures.empty or rw_chain.empty:
        st.error("Insufficient data for strategy generation. Adjust date range or load data again.")
        st.stop()

    # Institutional context (already existing architecture)
    rw_sentiment = ia.generate_sentiment(rw_futures, rw_chain, rw_pcr)

    # Build engines
    option_regime = sb.detect_option_seller_regime(rw_futures, rw_chain, rw_pcr, rw_sentiment)
    option_ideas = sb.generate_option_seller_strategies(rw_chain, option_regime)
    market_structure = sb.detect_market_structure(rw_futures)
    futures_ideas = sb.generate_institutional_strategies(market_structure, rw_chain)
    compact_summary = sb.build_strategy_summary(option_regime, option_ideas, market_structure, futures_ideas)

    # ---------- C) Strategy Summary Panel ----------
    st.subheader("Strategy Summary Panel")
    s1, s2, s3 = st.columns([2, 2, 3])
    s1.metric("Market Regime", option_regime["regime"])
    s2.metric("Institutional Structure", market_structure["structure"])
    s3.metric("Top Suggested Strategy", compact_summary["suggested_strategy"])

    st.code(
        "\n".join([
            f"Entry:   {compact_summary['entry']}",
            f"SL:      {compact_summary['stop_loss']}",
            f"Target:  {compact_summary['target']}",
            f"Risk:    {compact_summary['risk_note']}",
        ]),
        language="text")

    st.divider()

    # ---------- A) Option Seller Strategy Engine ----------
    st.subheader("A) Option Seller Strategy Engine")
    st.caption("Uses option chain + PCR + OI + trend/volatility context to suggest premium-selling setups.")

    ocol1, ocol2, ocol3, ocol4 = st.columns(4)
    ocol1.metric("Detected Regime", option_regime["regime"])
    ocol2.metric("PCR (current)", f"{option_regime['pcr_now']:.3f}")
    ocol3.metric("ATM IV", f"{option_regime['atm_iv']:.2f}%")
    ocol4.metric("Trend Strength", f"{option_regime['trend_strength_pct']:.2f}%")

    st.caption(
        f"OI Walls: Support {option_regime.get('pe_wall', 'N/A')} | "
        f"Resistance {option_regime.get('ce_wall', 'N/A')} | "
        f"Vol regime: {option_regime['vol_regime']} / IV regime: {option_regime['iv_regime']}"
    )

    option_df = sb.to_dataframe(option_ideas)
    if not option_df.empty:
        st.dataframe(
            option_df[[
                "strategy_name", "instrument", "direction", "strike_or_level", "premium_or_price",
                "entry_reason", "stop_loss_rule", "target_rule", "risk_level", "expected_time_to_target",
            ]],
            width='stretch',
            hide_index=True,
            height=320)

        with st.expander("Detailed assumptions & risks (Option Seller)"):
            st.dataframe(
                option_df[["strategy_name", "fit_conditions", "main_risks", "assumptions"]],
                width='stretch',
                hide_index=True)

    # Optional visual: CE/PE OI distribution with suggested range markers
    ov1, ov2 = st.columns(2)
    with ov1:
        st.markdown("**Option Chain OI Distribution**")
        oi_fig = go.Figure()
        oi_fig.add_trace(go.Bar(x=rw_chain["strike"], y=rw_chain["CE_OI"], name="CE OI", opacity=0.7))
        oi_fig.add_trace(go.Bar(x=rw_chain["strike"], y=rw_chain["PE_OI"], name="PE OI", opacity=0.7))
        if option_regime.get("ce_wall"):
            oi_fig.add_vline(x=option_regime["ce_wall"], line_dash="dash", line_color="red", annotation_text="CE Wall")
        if option_regime.get("pe_wall"):
            oi_fig.add_vline(x=option_regime["pe_wall"], line_dash="dash", line_color="green", annotation_text="PE Wall")
        oi_fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(oi_fig, width='stretch')

    with ov2:
        st.markdown("**PCR Context**")
        pcr_fig = go.Figure()
        pcr_fig.add_trace(go.Scatter(x=rw_pcr["date"], y=rw_pcr["pcr_oi"], name="PCR OI", line=dict(width=2)))
        pcr_fig.add_hline(y=1.25, line_dash="dash", line_color="red")
        pcr_fig.add_hline(y=0.75, line_dash="dash", line_color="green")
        pcr_fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(pcr_fig, width='stretch')

    st.divider()

    # ---------- B) Institutional Trader Strategy Engine ----------
    st.subheader("B) Institutional-style Futures Trader Engine")
    st.caption("Uses structure (HH/LL), volume confirmation, and volatility regime.")

    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    fcol1.metric("Market Structure", market_structure["structure"])
    fcol2.metric("Bias", market_structure["bias"])
    fcol3.metric("Volume Confirmation", market_structure["volume_confirmation"])
    fcol4.metric("Volatility Regime", market_structure["volatility_regime"])

    st.caption(
        f"Swing High: ₹{market_structure['swing_high']:,.0f} | "
        f"Swing Low: ₹{market_structure['swing_low']:,.0f} | "
        f"ATR: {market_structure['atr']:.1f}"
    )

    futures_df_ideas = sb.to_dataframe(futures_ideas)
    if not futures_df_ideas.empty:
        st.dataframe(
            futures_df_ideas[[
                "strategy_name", "instrument", "direction", "strike_or_level", "premium_or_price",
                "entry_reason", "stop_loss_rule", "target_rule", "risk_level", "expected_time_to_target",
            ]],
            width='stretch',
            hide_index=True,
            height=320)

        with st.expander("Detailed assumptions & risks (Institutional-style Futures)"):
            st.dataframe(
                futures_df_ideas[["strategy_name", "fit_conditions", "main_risks", "assumptions"]],
                width='stretch',
                hide_index=True)

    # Optional visual: structure chart
    st.markdown("**Market Structure Snapshot (Price + Swing Levels)**")
    str_fig = go.Figure()
    str_fig.add_trace(go.Scatter(x=rw_futures["date"], y=rw_futures["close"], name="Close", line=dict(width=2)))
    str_fig.add_hline(y=market_structure["swing_high"], line_dash="dash", line_color="red", annotation_text="Swing High")
    str_fig.add_hline(y=market_structure["swing_low"], line_dash="dash", line_color="green", annotation_text="Swing Low")
    str_fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(str_fig, width='stretch')

    with st.expander("Why these rules make sense (educational note)"):
        st.markdown(
            "\n".join([
                "- Option seller setups are selected when trend strength is moderate/low and IV/OI context supports mean reversion.",
                "- Credit spreads and iron condor appear when range and support/resistance walls are visible in OI data.",
                "- Futures ideas rely on structure (HH/HL vs LL/LH), breakout levels, and volume confirmation.",
                "- Stops are rule-based using ATR/level invalidation, and targets are simple ATR-multiple objectives.",
                "- These are not signals or advice; they are templates for study and journaling.",
            ])
        )


# ============================================================
#  TAB 5 — Option Buyers & Hedging Strategies
# ============================================================

with tab5:
    st.header(f"🛒 Option Buyers & Hedging Strategies — {symbol}")
    st.caption(
        "Educational, rule-based strategy ideas for buying options and for "
        "low-risk, defined-return hedging setups. Paper-trade / study only."
    )
    st.info(
        "💡 **Reading guide:**\n"
        "- **Option Buyer strategies** = pay a premium, profit from a big move.\n"
        "- **Hedging / Conservative strategies** = *collect* premium, profit from time decay & stability.\n"
        "Both have clearly defined max loss. Neither guarantees profit in real markets."
    )

    # Load data (reuse same pipeline)
    try:
        ob_futures = dp.get_futures_history(symbol, start_date, end_date)
        ob_pcr     = dp.get_pcr(symbol, start_date, end_date)
        ob_dates   = dp.get_available_option_dates(symbol)
        ob_valid   = ob_dates if st.session_state.get("real_data_loaded") else [
            d for d in ob_dates if str(d) <= end_date and str(d) >= start_date
        ]
        ob_date = st.selectbox(
            "Option Chain Date",
            options=ob_valid[::-1] if ob_valid else ["No data"],
            format_func=str,
            key="ob_chain_date")
        ob_chain = dp.get_option_chain(symbol, str(ob_date)) if ob_valid else pd.DataFrame()
    except Exception as exc:
        st.error(f"Error loading data: {exc}")
        st.stop()

    if ob_futures.empty or ob_chain.empty:
        st.error("Insufficient data. Load data files or check date range.")
        st.stop()

    ob_sentiment = ia.generate_sentiment(ob_futures, ob_chain, ob_pcr)
    buyer_regime = assess_buyer_regime(ob_futures, ob_chain, ob_sentiment)
    buyer_ideas  = generate_buyer_strategies(ob_chain, ob_futures, ob_sentiment, lot_size, cfg)
    hedge_ideas  = generate_hedging_strategies(ob_chain, ob_futures, ob_sentiment, lot_size, cfg)

    # Regime guidance banner
    spot_ob = float(ob_chain["spot"].iloc[0])
    bc1, bc2, bc3 = st.columns(3)
    bc1.metric("ATM IV", f"{buyer_regime['atm_iv']:.1f}%")
    bc2.metric("Sentiment", buyer_regime["sentiment"], delta=f"Score {buyer_regime['score']}")
    bc3.metric("Spot", f"₹{spot_ob:,.2f}")

    st.markdown(f"""
| | |
|---|---|
| **IV signal** | {buyer_regime["iv_guidance"]} |
| **Strategy guidance** | {buyer_regime["strategy_guidance"]} |
""")
    st.divider()

    # ---- A) Option Buyer Strategies ----
    st.subheader("A) Option Buyer Strategies — Pay Premium, Profit from Big Move")
    st.caption(
        "Maximum loss = premium paid only. No SPAN margin required for buyers. "
        "Best used when ATM IV is LOW (< 18%) or before a known event."
    )

    for idea in buyer_ideas:
        colour = {"Bullish": "🟢", "Bearish": "🔴", "Moderately Bullish": "🟡",
                  "Moderately Bearish": "🟠", "Neutral / Big Move Expected": "🔵",
                  "Neutral / Very Large Move Expected": "⚪"}.get(idea.direction, "⚪")
        with st.expander(f"{colour} {idea.strategy_name} — {idea.direction} | {idea.category}", expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**Instrument:** {idea.instrument}")
            c2.markdown(f"**Risk Level:** {idea.risk_level}")
            c3.markdown(f"**Expected Time:** {idea.expected_time}")

            with st.container(border=True):
                e1, e2, e3, e4 = st.columns(4)
                e1.metric("Entry", idea.entry_price.split("  ")[0])
                e2.metric("Stop-Loss", idea.stop_loss_rule.split(" ")[3] if "₹" in idea.stop_loss_rule else "See rule")
                e3.metric("Max Loss/Lot", idea.max_loss_per_lot)
                e4.metric("Max Gain/Lot", idea.max_gain_per_lot)

            st.markdown(f"**Strikes:** {idea.strikes_desc}")
            st.markdown(f"**Breakeven Move Required:** {idea.breakeven_move_pct}")
            st.markdown(f"**Win Condition:** {idea.win_condition}")
            st.markdown(f"**Stop-Loss Rule:** {idea.stop_loss_rule}")
            st.markdown(f"**Target Rule:** {idea.target_rule}")
            st.markdown(f"**Margin Required:** {idea.margin_required}")

            st.markdown("---")
            col_left, col_right = st.columns(2)
            col_left.markdown(f"**When to use:** {idea.when_to_use}")
            col_left.markdown(f"**IV preference:** {idea.iv_preference}")
            col_right.markdown(f"**Greeks note:** {idea.greeks_note}")
            col_right.markdown(f"**Main risks:** {idea.main_risks}")

            # Log button
            with st.form(f"log_buyer_{idea.strategy_name[:20].replace(' ', '_')}"):
                qty_b = st.number_input("Qty lots", 1, 20, 1, key=f"qty_b_{idea.strategy_name[:15]}")
                note_b = st.text_input("Notes", key=f"note_b_{idea.strategy_name[:15]}")
                if st.form_submit_button("📝 Log this Buyer Trade (Paper)"):
                    trade_id = tt.add_trade(
                        symbol=symbol,
                        instrument=idea._opt_type,
                        direction=idea._direction_code,
                        strike=idea._strike,
                        entry_price=idea._entry,
                        stop_loss=idea._sl,
                        target=idea._target,
                        qty_lots=qty_b,
                        lot_size=lot_size,
                        strategy_type=f"Option Buyer — {idea.strategy_name}",
                        regime=ob_sentiment.get("label", "N/A"),
                        structure=sb.detect_market_structure(ob_futures).get("structure", "N/A"),
                        reason=idea.when_to_use[:200],
                        expected_time=idea.expected_time,
                        margin_approx=idea.margin_required,
                        notes=note_b)
                    st.success(f"✅ Trade logged! ID: `{trade_id}` — check Trade Journal tab.")

    st.divider()

    # ---- B) Hedging / Conservative Strategies ----
    st.subheader("B) Hedging & Conservative Strategies — Defined Risk, Small Reliable Return")
    st.caption(
        "These strategies COLLECT premium (credit) upfront. "
        "Time decay works in your favour. Max loss is defined and known before entry. "
        "Win probability typically 60–75%."
    )

    for hidea in hedge_ideas:
        icon = "⭐" if "⭐" in hidea.strategy_name else "🛡️"
        with st.expander(f"{icon} {hidea.strategy_name} | {hidea.category}", expanded=False):
            h1, h2, h3 = st.columns(3)
            h1.markdown(f"**Direction:** {hidea.direction}")
            h2.markdown(f"**Instrument:** {hidea.instrument}")
            h3.markdown(f"**Expected Time:** {hidea.expected_time}")

            with st.container(border=True):
                # Highlight credit/debit
                credit_val = hidea.net_credit_or_debit
                st.markdown(f"### {credit_val}")
                st.caption("Positive = income received upfront | Negative = cost paid upfront")

                hc1, hc2 = st.columns(2)
                hc1.metric("Max Gain / Lot", hidea.max_gain_per_lot)
                hc2.metric("Max Loss / Lot", hidea.max_loss_per_lot)

            st.markdown(f"**Strikes:** {hidea.strikes_desc}")
            st.markdown(f"**Entry:** {hidea.entry_description}")
            st.markdown(f"**Stop-Loss:** {hidea.sl_rule}")
            st.markdown(f"**Target:** {hidea.target_rule}")
            st.markdown(f"**Win Probability (approx):** {hidea.win_probability_note}")
            st.markdown(f"**Margin Required:** {hidea.margin_required}")

            st.markdown("---")
            hcl, hcr = st.columns(2)
            hcl.markdown(f"**When to use:** {hidea.when_to_use}")
            hcl.markdown(f"**Market conditions:** {hidea.market_conditions}")
            hcl.markdown(f"**IV preference:** {hidea.iv_preference}")
            hcr.markdown(f"**Greeks note:** {hidea.greeks_note}")
            hcr.markdown(f"**Main risks:** {hidea.main_risks}")

    st.divider()
    with st.expander("📖 Key difference: Buyer vs Seller vs Hedger"):
        st.markdown("""
| | Option Buyer | Option Seller | Hedger (Credit Spread) |
|---|---|---|---|
| **Premium** | Pays premium | Receives premium | Receives net credit |
| **Max Loss** | Premium paid only | Theoretically unlimited (naked) | Spread width − credit (defined) |
| **Max Gain** | Unlimited (call) / Large (put) | Premium received | Net credit only |
| **Theta** | Enemy (loses value daily) | Friend (gains daily) | Friend (net positive) |
| **IV preference** | Buy when IV LOW | Sell when IV HIGH | Sell when IV HIGH |
| **Win condition** | Big directional move | Market stays in range | Market stays beyond sold strikes |
| **Best for** | Strong trend, event plays | Calm / range-bound markets | Consistent small income, defined risk |

**The hedging strategies (Bull Put Spread, Bear Call Spread, Iron Condor) offer a "best-of-both-worlds":**
- Risk is DEFINED (unlike naked selling)
- Income is collected upfront
- Time decay works in your favour
- Win probability is ~65-75%

However, their risk:reward ratio is typically 3:1 or 4:1 (risk more to make less) — this is compensated by high win probability.
        """)


# ============================================================
#  TAB 6 — Final Trade Decision
# ============================================================

with tab6:
    st.header(f"🎯 Final Trade Decision — {symbol}")
    st.caption(
        "Clean, minimal paper-trade setup generated from all loaded analysis. "
        "Study only — no real orders."
    )
    st.info(
        "⚠️  **PAPER-TRADE ONLY** — All figures here are educational approximations. "
        "Margins, premiums, and levels must be verified with your broker before any real trade."
    )

    try:
        ftd_futures = dp.get_futures_history(symbol, start_date, end_date)
        ftd_pcr     = dp.get_pcr(symbol, start_date, end_date)
        ftd_chain_dates = dp.get_available_option_dates(symbol)
        ftd_valid = ftd_chain_dates if st.session_state.get("real_data_loaded") else [
            d for d in ftd_chain_dates if str(d) <= end_date and str(d) >= start_date
        ]
        ftd_chain_date = st.selectbox(
            "Option Chain Date",
            options=ftd_valid[::-1] if ftd_valid else ["No data"],
            format_func=str,
            key="ftd_chain_date")
        ftd_chain = dp.get_option_chain(symbol, str(ftd_chain_date)) if ftd_valid else pd.DataFrame()
    except Exception as exc:
        st.error(f"Error loading data: {exc}")
        st.stop()

    if ftd_futures.empty or ftd_chain.empty:
        st.error("Insufficient data. Load data files or check date range.")
        st.stop()

    _ftd_expiry = str(ftd_chain["date"].iloc[0].date()) if "date" in ftd_chain.columns else str(ftd_chain_date)

    # Generate analysis
    ftd_sentiment = ia.generate_sentiment(ftd_futures, ftd_chain, ftd_pcr)
    ftd_option_regime = sb.detect_option_seller_regime(ftd_futures, ftd_chain, ftd_pcr, ftd_sentiment)
    ftd_option_ideas  = sb.generate_option_seller_strategies(ftd_chain, ftd_option_regime)

    inst_decision   = institutional_trade(ftd_futures, ftd_chain, ftd_sentiment, lot_size, cfg, budget_inr=capital_budget)
    seller_decision = option_seller_trade(ftd_futures, ftd_chain, ftd_sentiment, ftd_option_ideas, lot_size, cfg, budget_inr=capital_budget)

    # ----- A) Institutional Logic -----
    st.subheader("A) Institutional Trader Logic")
    if "error" in inst_decision:
        st.warning(inst_decision["error"])
    else:
        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("Sentiment", inst_decision["sentiment_label"], delta=f"Score {inst_decision['sentiment_score']}")
        ic2.metric("Direction", inst_decision["direction"])
        ic3.metric("Risk Level", inst_decision["risk_level"])

        with st.container(border=True):
            st.markdown(f"**Instrument:** {inst_decision['instrument']}")
            fc1, fc2, fc3, fc4 = st.columns(4)
            fc1.metric("Entry", inst_decision["futures_entry"])
            fc2.metric("Stop-Loss", inst_decision["futures_sl"])
            fc3.metric("Target 1", inst_decision["futures_target1"])
            fc4.metric("Target 2", inst_decision["futures_target2"])

            st.markdown(f"**Margin (positional):** {inst_decision['futures_margin']}  "
                        f"&nbsp;|&nbsp; **Intraday:** {inst_decision['futures_margin_intraday']}")
            st.markdown(f"**Risk:Reward:** {inst_decision['risk_reward']}")
            st.markdown(f"**Expected Time:** {inst_decision['expected_time']}")

        with st.container(border=True):
            st.markdown(f"**Options Alternative — {inst_decision['option_type']} {inst_decision['option_strike']}**")
            oc1, oc2, oc3, oc4 = st.columns(4)
            oc1.metric("Premium", inst_decision["option_premium"])
            oc2.metric("Stop-Loss", inst_decision["option_sl"])
            oc3.metric("Target", inst_decision["option_target"])
            oc4.metric("Margin", inst_decision["option_margin"])
            st.caption(f"IV at strike: {inst_decision['option_iv']}")

        st.markdown(f"**Entry Reason:** {inst_decision['reason']}")
        with st.expander("Trade Invalidation Conditions"):
            for cond in inst_decision["invalid_conditions"]:
                st.markdown(f"- {cond}")

        # Log button — Institutional
        st.markdown("---")
        _inst_rec  = min(inst_decision.get("recommended_lots", 1), 50)
        _inst_mpl  = inst_decision.get("_margin_per_lot_option", 0)
        st.caption(
            f"Budget ₹{capital_budget:,.0f} → **{_inst_rec} lot(s)** recommended "
            f"(option path ~₹{_inst_mpl * _inst_rec:,.0f} total)"
        )
        if st.button("Generate Groww Ticket (Institutional)", key="groww_btn_inst"):
            _inst_ticket = _build_groww_ticket_text(
                setup_name="Institutional Option Alternative",
                symbol_name=symbol,
                expiry=_ftd_expiry,
                lots=int(_inst_rec),
                lot_sz=int(lot_size),
                entry=float(inst_decision.get("_entry_price", 0) or 0),
                stop_loss=float(inst_decision.get("_sl_price", 0) or 0),
                target=float(inst_decision.get("_target_price", 0) or 0),
                direction=str(inst_decision.get("_direction", "buy")),
                legs=[
                    {
                        "action": "BUY" if str(inst_decision.get("_direction", "buy")).lower() == "buy" else "SELL",
                        "option_type": str(inst_decision.get("_opt_type", "CE")),
                        "strike": str(inst_decision.get("_strike", "")),
                    }
                ],
                note=str(inst_decision.get("reason", ""))[:220])
            st.session_state["groww_ticket_inst"] = _inst_ticket
        if st.session_state.get("groww_ticket_inst"):
            _render_groww_ticket_ui(st.session_state["groww_ticket_inst"], "inst")
        with st.form("log_inst_trade"):
            qty_inst = st.number_input("Qty (lots)", 1, 50, _inst_rec, key="qty_inst")
            notes_inst = st.text_input("Optional notes", key="notes_inst")
            if st.form_submit_button("📝 Log This Institutional Trade (Paper)", type="primary"):
                regime_str  = ftd_sentiment.get("label", "N/A")
                struct_str  = sb.detect_market_structure(ftd_futures).get("structure", "N/A")
                trade_id = tt.add_trade(
                    symbol=symbol,
                    instrument=inst_decision["_opt_type"],
                    direction=inst_decision["_direction"],
                    strike=inst_decision["_strike"],
                    entry_price=inst_decision["_entry_price"],
                    stop_loss=inst_decision["_sl_price"],
                    target=inst_decision["_target_price"],
                    qty_lots=qty_inst,
                    lot_size=lot_size,
                    strategy_type="Institutional",
                    regime=regime_str,
                    structure=struct_str,
                    reason=inst_decision["reason"][:200],
                    expected_time=inst_decision["expected_time"],
                    margin_approx=inst_decision["option_margin"],
                    notes=notes_inst)
                st.success(f"✅ Trade logged! ID: `{trade_id}` — check **Trade Journal** tab.")
                logger.info("Institutional trade logged: %s | %s | ₹%.2f",
                            trade_id, symbol, inst_decision["_entry_price"])

    st.divider()

    # ----- B) Option Seller Logic -----
    st.subheader("B) Option Seller Logic")
    if "error" in seller_decision:
        st.warning(seller_decision["error"])
    else:
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Strategy", seller_decision["strategy"])
        sc2.metric("Total Credit", seller_decision["total_credit"])
        sc3.metric("Risk Level", seller_decision["risk_level"])

        with st.container(border=True):
            st.markdown(f"**{seller_decision['description']}**")
            sc4, sc5, sc6, sc7 = st.columns(4)
            sc4.metric("Credit/unit", seller_decision["total_credit"])
            sc5.metric("Credit/lot", seller_decision["total_credit_lot"])
            sc6.metric("Target (50% decay)", seller_decision["target_rule"].split("₹")[-1].split(" ")[0] if "₹" in seller_decision["target_rule"] else "—")
            sc7.metric("Margin", seller_decision["margin_required"])

        with st.container(border=True):
            col_a, col_b = st.columns(2)
            col_a.markdown(f"**SL Rule:** {seller_decision['sl_rule']}")
            col_b.markdown(f"**Target Rule:** {seller_decision['target_rule']}")
            st.markdown(f"**Profit Zone:** {seller_decision['profit_range']}")
            st.markdown(f"**Expected Time:** {seller_decision['expected_time']}")

        st.markdown(f"**Entry Reason:** {seller_decision['reason']}")
        with st.expander("Trade Invalidation Conditions"):
            for cond in seller_decision["invalid_conditions"]:
                st.markdown(f"- {cond}")

        # Log button — Option Seller
        st.markdown("---")
        _sell_rec = min(seller_decision.get("recommended_lots", 1), 50)
        _sell_mpl = seller_decision.get("_margin_per_lot", 0)
        st.caption(
            f"Budget ₹{capital_budget:,.0f} → **{_sell_rec} lot(s)** recommended "
            f"(~₹{_sell_mpl * _sell_rec:,.0f} total margin)"
        )
        if st.button("Generate Groww Ticket (Option Seller)", key="groww_btn_seller"):
            _legs = []
            _short_pe = seller_decision.get("short_pe_strike") or seller_decision.get("_strike_pe")
            _short_ce = seller_decision.get("short_ce_strike") or seller_decision.get("_strike_ce")
            _buy_pe = seller_decision.get("buy_pe_strike")
            _buy_ce = seller_decision.get("buy_ce_strike")

            if _buy_pe:
                _legs.append({"action": "BUY", "option_type": "PE", "strike": str(_buy_pe)})
            if _short_pe:
                _legs.append({"action": "SELL", "option_type": "PE", "strike": str(_short_pe)})
            if _short_ce:
                _legs.append({"action": "SELL", "option_type": "CE", "strike": str(_short_ce)})
            if _buy_ce:
                _legs.append({"action": "BUY", "option_type": "CE", "strike": str(_buy_ce)})

            _seller_ticket = _build_groww_ticket_text(
                setup_name=str(seller_decision.get("strategy", "Option Seller Setup")),
                symbol_name=symbol,
                expiry=_ftd_expiry,
                lots=int(_sell_rec),
                lot_sz=int(lot_size),
                entry=float(seller_decision.get("_entry_price", 0) or 0),
                stop_loss=float(seller_decision.get("_sl_price", 0) or 0),
                target=float(seller_decision.get("_target_price", 0) or 0),
                direction=str(seller_decision.get("_direction", "sell")),
                legs=_legs,
                note=str(seller_decision.get("reason", ""))[:220])
            st.session_state["groww_ticket_seller"] = _seller_ticket
        if st.session_state.get("groww_ticket_seller"):
            _render_groww_ticket_ui(st.session_state["groww_ticket_seller"], "seller")
        with st.form("log_seller_trade"):
            qty_sell = st.number_input("Qty (lots)", 1, 50, _sell_rec, key="qty_sell")
            notes_sell = st.text_input("Optional notes", key="notes_sell")
            if st.form_submit_button("📝 Log This Option Seller Trade (Paper)", type="primary"):
                regime_str = ftd_option_regime.get("regime", "N/A")
                struct_str = sb.detect_market_structure(ftd_futures).get("structure", "N/A")
                trade_id = tt.add_trade(
                    symbol=symbol,
                    instrument=seller_decision["_opt_type"],
                    direction=seller_decision["_direction"],
                    strike=f"CE:{seller_decision['_strike_ce']}/PE:{seller_decision['_strike_pe']}",
                    entry_price=seller_decision["_entry_price"],
                    stop_loss=seller_decision["_sl_price"],
                    target=seller_decision["_target_price"],
                    qty_lots=qty_sell,
                    lot_size=lot_size,
                    strategy_type="Option Seller",
                    regime=regime_str,
                    structure=struct_str,
                    reason=seller_decision["reason"][:200],
                    expected_time=seller_decision["expected_time"],
                    margin_approx=seller_decision["margin_required"],
                    notes=notes_sell)
                st.success(f"✅ Trade logged! ID: `{trade_id}` — check **Trade Journal** tab.")
                logger.info("Option seller trade logged: %s | %s | credit ₹%.2f",
                            trade_id, symbol, seller_decision["_entry_price"])


    st.divider()

    # ----- C) Option Buyer Logic -----
    st.subheader("C) Option Buyer Logic")
    st.caption(
        "Best single buyer setup right now, auto-selected from 6 candidates by "
        "matching sentiment + IV level. Max loss = premium paid only. No SPAN margin."
    )

    ftd_buyer_ideas  = generate_buyer_strategies(ftd_chain, ftd_futures, ftd_sentiment, lot_size, cfg)
    ftd_hedge_ideas  = generate_hedging_strategies(ftd_chain, ftd_futures, ftd_sentiment, lot_size, cfg)
    ftd_buyer_regime = assess_buyer_regime(ftd_futures, ftd_chain, ftd_sentiment)

    # Pick the single most relevant buyer idea given direction + IV
    _score = ftd_sentiment.get("score", 0)
    _best_buyer = None
    for _idea in ftd_buyer_ideas:
        if _best_buyer is None:
            _best_buyer = _idea   # fallback to first
        if _score >= 1 and "Bullish" in _idea.direction:
            _best_buyer = _idea
            break
        if _score <= -1 and "Bearish" in _idea.direction:
            _best_buyer = _idea
            break

    # Pick best hedge: prefer ⭐ marked (highest win-probability)
    _best_hedge = next((h for h in ftd_hedge_ideas if "⭐" in h.strategy_name), None)
    if _best_hedge is None and ftd_hedge_ideas:
        _best_hedge = ftd_hedge_ideas[0]

    st.info(
        f"**{ftd_buyer_regime.get('iv_guidance', '')}**  |  "
        f"Sentiment: **{ftd_sentiment.get('label', 'Neutral')}**  |  "
        f"ATM IV: **{ftd_buyer_regime.get('atm_iv', 0):.1f}%**"
    )

    if _best_buyer:
        with st.container(border=True):
            st.markdown(f"#### 🎯 Recommended Buyer Trade: {_best_buyer.strategy_name}")
            st.caption(f"{_best_buyer.category} | {_best_buyer.direction} | Risk: {_best_buyer.risk_level}")

            bm1, bm2, bm3, bm4 = st.columns(4)
            bm1.metric("Premium (Entry)", f"₹{_best_buyer._entry:.2f}")
            bm2.metric("Stop-Loss", f"₹{_best_buyer._sl:.2f}")
            bm3.metric("Target", f"₹{_best_buyer._target:.2f}")
            bm4.metric("Max Loss / Lot", _best_buyer.max_loss_per_lot)

            with st.container(border=True):
                st.markdown(f"**Strikes:** {_best_buyer.strikes_desc}")
                st.markdown(f"**Breakeven move required:** {_best_buyer.breakeven_move_pct}")
                st.markdown(f"**Win condition:** {_best_buyer.win_condition}")

            col_bl, col_br = st.columns(2)
            col_bl.markdown(f"**SL rule:** {_best_buyer.stop_loss_rule}")
            col_bl.markdown(f"**Target rule:** {_best_buyer.target_rule}")
            col_bl.markdown(f"**Margin needed:** {_best_buyer.margin_required}")
            col_br.markdown(f"**Expected time:** {_best_buyer.expected_time}")
            col_br.markdown(f"**IV preference:** {_best_buyer.iv_preference}")
            col_br.markdown(f"**Why now:** {_best_buyer.when_to_use}")

            with st.expander("Greeks & main risks"):
                st.markdown(f"**Greeks:** {_best_buyer.greeks_note}")
                st.markdown(f"**Main risks:** {_best_buyer.main_risks}")

            _buyer_mpl  = max(_best_buyer._entry * lot_size, 1)
            _buyer_rec  = min(max(1, int(capital_budget / _buyer_mpl)), 50)
            st.caption(
                f"Budget ₹{capital_budget:,.0f} → **{_buyer_rec} lot(s)** recommended "
                f"(~₹{_buyer_mpl * _buyer_rec:,.0f} total premium)"
            )
            if st.button("Generate Groww Ticket (Buyer)", key="groww_btn_buyer"):
                _buyer_ticket = _build_groww_ticket_text(
                    setup_name=str(_best_buyer.strategy_name),
                    symbol_name=symbol,
                    expiry=_ftd_expiry,
                    lots=int(_buyer_rec),
                    lot_sz=int(lot_size),
                    entry=float(getattr(_best_buyer, "_entry", 0) or 0),
                    stop_loss=float(getattr(_best_buyer, "_sl", 0) or 0),
                    target=float(getattr(_best_buyer, "_target", 0) or 0),
                    direction=str(getattr(_best_buyer, "_direction_code", "buy")),
                    legs=[
                        {
                            "action": "BUY" if str(getattr(_best_buyer, "_direction_code", "buy")).lower() == "buy" else "SELL",
                            "option_type": str(getattr(_best_buyer, "_opt_type", "CE")),
                            "strike": str(getattr(_best_buyer, "_strike", "")),
                        }
                    ],
                    note=str(getattr(_best_buyer, "when_to_use", ""))[:220])
                st.session_state["groww_ticket_buyer"] = _buyer_ticket
            if st.session_state.get("groww_ticket_buyer"):
                _render_groww_ticket_ui(st.session_state["groww_ticket_buyer"], "buyer")
            with st.form("log_ftd_buyer_trade"):
                qty_ftdb  = st.number_input("Qty (lots)", 1, 50, _buyer_rec, key="qty_ftdb")
                notes_ftdb = st.text_input("Optional notes", key="notes_ftdb")
                if st.form_submit_button("📝 Log This Buyer Trade (Paper)", type="primary"):
                    trade_id = tt.add_trade(
                        symbol=symbol,
                        instrument=_best_buyer._opt_type,
                        direction=_best_buyer._direction_code,
                        strike=_best_buyer._strike,
                        entry_price=_best_buyer._entry,
                        stop_loss=_best_buyer._sl,
                        target=_best_buyer._target,
                        qty_lots=qty_ftdb,
                        lot_size=lot_size,
                        strategy_type=f"Option Buyer — {_best_buyer.strategy_name}",
                        regime=ftd_sentiment.get("label", "N/A"),
                        structure=sb.detect_market_structure(ftd_futures).get("structure", "N/A"),
                        reason=_best_buyer.when_to_use[:200],
                        expected_time=_best_buyer.expected_time,
                        margin_approx=_best_buyer.margin_required,
                        notes=notes_ftdb)
                    st.success(f"✅ Trade logged! ID: `{trade_id}` — check **Trade Journal** tab.")

    # Best conservative hedge alongside the buyer
    if _best_hedge:
        st.divider()
        with st.container(border=True):
            st.markdown(f"#### 🛡️ Conservative Alternative / Hedge: {_best_hedge.strategy_name}")
            st.caption(
                "Use this instead of (or alongside) the buyer trade if you prefer "
                "defined-risk income over directional exposure."
            )
            hm1, hm2, hm3 = st.columns(3)
            hm1.metric("Income / Lot", _best_hedge.max_gain_per_lot)
            hm2.metric("Max Risk / Lot", _best_hedge.max_loss_per_lot)
            hm3.metric("Win Probability", _best_hedge.win_probability_note.split("(")[0].strip())

            st.markdown(f"**{_best_hedge.net_credit_or_debit}**")
            st.markdown(f"**Strikes:** {_best_hedge.strikes_desc}")
            st.markdown(f"**SL:** {_best_hedge.sl_rule}")
            st.markdown(f"**Target:** {_best_hedge.target_rule}")
            st.markdown(f"**Margin:** {_best_hedge.margin_required} | **Time:** {_best_hedge.expected_time}")

            _hedge_mpl = max(getattr(_best_hedge, "_entry", 0) * lot_size, 1)
            _hedge_rec = min(max(1, int(capital_budget / _hedge_mpl)), 50)
            st.caption(
                f"Budget ₹{capital_budget:,.0f} → **{_hedge_rec} lot(s)** recommended "
                f"(~₹{_hedge_mpl * _hedge_rec:,.0f} total)"
            )
            if st.button("Generate Groww Ticket (Hedge)", key="groww_btn_hedge"):
                _hedge_legs = []
                _h_sell_p = getattr(_best_hedge, "_strike_pe_sell", None)
                _h_buy_p = getattr(_best_hedge, "_strike_pe_buy", None)
                _h_sell_c = getattr(_best_hedge, "_strike_ce_sell", None)
                _h_buy_c = getattr(_best_hedge, "_strike_ce_buy", None)

                if _h_buy_p:
                    _hedge_legs.append({"action": "BUY", "option_type": "PE", "strike": str(_h_buy_p)})
                if _h_sell_p:
                    _hedge_legs.append({"action": "SELL", "option_type": "PE", "strike": str(_h_sell_p)})
                if _h_sell_c:
                    _hedge_legs.append({"action": "SELL", "option_type": "CE", "strike": str(_h_sell_c)})
                if _h_buy_c:
                    _hedge_legs.append({"action": "BUY", "option_type": "CE", "strike": str(_h_buy_c)})

                if not _hedge_legs:
                    _hedge_legs = [{
                        "action": "SELL" if str(getattr(_best_hedge, "_direction", "sell")).lower() == "sell" else "BUY",
                        "option_type": str(getattr(_best_hedge, "_opt_type", "CE")),
                        "strike": str(getattr(_best_hedge, "_strike_ce", "")),
                    }]

                _hedge_ticket = _build_groww_ticket_text(
                    setup_name=str(_best_hedge.strategy_name),
                    symbol_name=symbol,
                    expiry=_ftd_expiry,
                    lots=int(_hedge_rec),
                    lot_sz=int(lot_size),
                    entry=float(getattr(_best_hedge, "_entry", 0) or 0),
                    stop_loss=float(getattr(_best_hedge, "_sl", 0) or 0),
                    target=float(getattr(_best_hedge, "_target", 0) or 0),
                    direction=str(getattr(_best_hedge, "_direction", "sell")),
                    legs=_hedge_legs,
                    note=str(getattr(_best_hedge, "when_to_use", ""))[:220])
                st.session_state["groww_ticket_hedge"] = _hedge_ticket
            if st.session_state.get("groww_ticket_hedge"):
                _render_groww_ticket_ui(st.session_state["groww_ticket_hedge"], "hedge")
            with st.form("log_ftd_hedge_trade"):
                qty_ftdh  = st.number_input("Qty (lots)", 1, 50, _hedge_rec, key="qty_ftdh")
                notes_ftdh = st.text_input("Optional notes", key="notes_ftdh")
                if st.form_submit_button("📝 Log This Hedge Trade (Paper)", type="primary"):
                    trade_id = tt.add_trade(
                        symbol=symbol,
                        instrument=getattr(_best_hedge, "_opt_type", "CE+PE"),
                        direction=getattr(_best_hedge, "_direction", "sell"),
                        strike=getattr(_best_hedge, "_strike_ce", 0),
                        entry_price=getattr(_best_hedge, "_entry", 0.0),
                        stop_loss=getattr(_best_hedge, "_sl", 0.0),
                        target=getattr(_best_hedge, "_target", 0.0),
                        qty_lots=qty_ftdh,
                        lot_size=lot_size,
                        strategy_type=f"Hedge — {_best_hedge.strategy_name}",
                        regime=ftd_sentiment.get("label", "N/A"),
                        structure=sb.detect_market_structure(ftd_futures).get("structure", "N/A"),
                        reason=_best_hedge.when_to_use[:200],
                        expected_time=_best_hedge.expected_time,
                        margin_approx=_best_hedge.margin_required,
                        notes=notes_ftdh)
                    st.success(f"✅ Trade logged! ID: `{trade_id}` — check **Trade Journal** tab.")

    # Side-by-side summary of all three logics
    st.divider()
    st.subheader("📊 All Three Logics — Side-by-Side Comparison")
    _rows = []
    if "error" not in inst_decision:
        _rows.append({
            "Logic": "A) Institutional",
            "Instrument": inst_decision["instrument"].split(" or ")[0],
            "Entry": inst_decision["futures_entry"],
            "SL": inst_decision["futures_sl"],
            "Target": inst_decision["futures_target1"],
            "Max Loss/Lot": "1.5 × ATR × lot",
            "Margin": inst_decision["futures_margin"],
            "Risk": inst_decision["risk_level"],
            "Time": inst_decision["expected_time"],
        })
    if "error" not in seller_decision:
        _rows.append({
            "Logic": "B) Option Seller",
            "Instrument": seller_decision["strategy"],
            "Entry": f"Collect {seller_decision['total_credit']}",
            "SL": "Premium doubles",
            "Target": "50% credit decay",
            "Max Loss/Lot": seller_decision["margin_required"],
            "Margin": seller_decision["margin_required"],
            "Risk": seller_decision["risk_level"],
            "Time": seller_decision["expected_time"],
        })
    if _best_buyer:
        _rows.append({
            "Logic": "C) Option Buyer",
            "Instrument": f"{_best_buyer._opt_type} {_best_buyer._strike}",
            "Entry": f"\u20b9{_best_buyer._entry:.2f}",
            "SL": f"\u20b9{_best_buyer._sl:.2f}",
            "Target": f"\u20b9{_best_buyer._target:.2f}",
            "Max Loss/Lot": _best_buyer.max_loss_per_lot,
            "Margin": _best_buyer.margin_required,
            "Risk": _best_buyer.risk_level,
            "Time": _best_buyer.expected_time,
        })
    if _best_hedge:
        _rows.append({
            "Logic": "D) Hedging (Credit Spread)",
            "Instrument": _best_hedge.strikes_desc[:40] + ".." if len(_best_hedge.strikes_desc) > 40 else _best_hedge.strikes_desc,
            "Entry": _best_hedge.net_credit_or_debit.split("\u20b9")[1].split(" ")[0] if "\u20b9" in _best_hedge.net_credit_or_debit else "Credit",
            "SL": _best_hedge.sl_rule[:35] + ".." if len(_best_hedge.sl_rule) > 35 else _best_hedge.sl_rule,
            "Target": "70-80% profit",
            "Max Loss/Lot": _best_hedge.max_loss_per_lot,
            "Margin": _best_hedge.margin_required,
            "Risk": "Low (Defined)",
            "Time": _best_hedge.expected_time,
        })
    if _rows:
        st.dataframe(pd.DataFrame(_rows), hide_index=True, width='stretch')


# ============================================================
#  TAB 7 — Trade Journal
# ============================================================

with tab7:
    st.header("📓 Trade Journal")
    st.caption(
        "Paper-trade log. Upload new data files anytime to see live P&L, "
        "HOLD/EXIT suggestions, and auto-close when SL/Target is hit."
    )
    st.info(
        "ℹ️  **How it works:** Log a trade on the Final Trade Decision tab → "
        "Come back here after uploading updated data files → "
        "P&L and suggestion auto-refreshes."
    )

    # Update open trades with latest data (runs every time this tab is visible)
    try:
        tj_futures = dp.get_futures_history(symbol, start_date, end_date)
        tj_chain   = dp.get_option_chain(symbol)
    except Exception:
        tj_futures = pd.DataFrame()
        tj_chain   = pd.DataFrame()

    open_trades = tt.update_all_open(tj_chain, tj_futures, symbol=symbol)

    # ---- Open Positions ----
    st.subheader(f"Open Positions — {symbol}")
    all_trades = tt.load_trades()
    open_sym   = [t for t in all_trades if t["status"] == "Open" and t["symbol"] == symbol]
    open_all   = [t for t in all_trades if t["status"] == "Open"]

    if not open_sym:
        st.info(f"No open trades for **{symbol}**. Other symbols: {len(open_all)} open position(s).")
    else:
        for trade in open_sym:
            pnl_val  = trade.get("total_pnl")
            pnl_str  = f"₹{pnl_val:,.0f}" if pnl_val is not None else "Pending"
            pnl_delta = f"{'+' if (pnl_val or 0) >= 0 else ''}{pnl_str}"
            sugg_icon = {"HOLD": "🟢", "MONITOR": "🟡", "EXIT (partial/full)": "🟠",
                         "REVIEW — Near Stop-Loss": "🔴", "EXIT — Stop-Loss Hit": "⛔",
                         "EXIT — Target Reached": "✅"}.get(trade.get("suggestion", ""), "⚪")

            with st.container(border=True):
                t1, t2, t3, t4, t5 = st.columns([2, 2, 2, 2, 3])
                t1.metric("Symbol", trade["symbol"])
                t2.metric("Instrument", f"{trade['instrument']} {trade.get('strike', '')}")
                t3.metric("Entry", f"₹{trade['entry_price']:.2f}")
                t4.metric("Current P&L", pnl_str, delta=pnl_delta)
                t5.markdown(
                    f"**{sugg_icon} {trade.get('suggestion', 'HOLD')}**\n\n"
                    f"{trade.get('suggestion_reason', '')}"
                )

                with st.expander("Trade details"):
                    det_cols = st.columns(3)
                    det_cols[0].markdown(
                        f"**SL:** ₹{trade['stop_loss']:.2f}\n\n"
                        f"**Target:** ₹{trade['target']:.2f}"
                    )
                    det_cols[1].markdown(
                        f"**Strategy:** {trade['strategy_type']}\n\n"
                        f"**Regime:** {trade['regime']}"
                    )
                    det_cols[2].markdown(
                        f"**Logged:** {trade['timestamp']}\n\n"
                        f"**Expected:** {trade.get('expected_time', 'N/A')}"
                    )
                    st.markdown(f"**Reason:** {trade.get('reason', '')}")
                    if trade.get("notes"):
                        st.markdown(f"**Notes:** {trade['notes']}")

                    with st.form(f"close_{trade['id']}"):
                        exit_px   = st.number_input("Exit price (manual close)", value=float(trade["entry_price"]), key=f"ep_{trade['id']}")
                        close_note = st.text_input("Exit notes", key=f"cn_{trade['id']}")
                        if st.form_submit_button("Close this trade"):
                            tt.close_trade(trade["id"], exit_px, close_note)
                            st.success("Trade closed. Refresh to see updated history.")
                            st.rerun()

    st.divider()

    # ---- Trade History ----
    st.subheader("Trade History (All Symbols — Today & Past)")

    hist_filter = st.selectbox("Filter by symbol", ["All"] + sorted({t["symbol"] for t in all_trades}),
                               key="hist_filter")
    hist_trades = [t for t in all_trades if hist_filter == "All" or t["symbol"] == hist_filter]

    if not hist_trades:
        st.info("No trades logged yet. Go to the **Final Trade Decision** tab to log your first paper trade.")
    else:
        # Summary metrics
        total_pnl  = sum(t.get("total_pnl") or 0 for t in hist_trades if t["status"] == "Closed")
        open_count = sum(1 for t in hist_trades if t["status"] == "Open")
        closed_count = sum(1 for t in hist_trades if t["status"] == "Closed")
        winners    = sum(1 for t in hist_trades if (t.get("total_pnl") or 0) > 0 and t["status"] == "Closed")

        hm1, hm2, hm3, hm4 = st.columns(4)
        hm1.metric("Total Closed P&L", f"₹{total_pnl:,.0f}")
        hm2.metric("Open Trades", open_count)
        hm3.metric("Closed Trades", closed_count)
        hm4.metric("Win Rate", f"{winners/closed_count*100:.0f}%" if closed_count else "N/A")

        hist_df = pd.DataFrame(hist_trades)
        display_cols = [c for c in [
            "id", "timestamp", "symbol", "instrument", "strike", "entry_price",
            "exit_price", "stop_loss", "target", "strategy_type",
            "status", "total_pnl", "suggestion",
        ] if c in hist_df.columns]
        display_df = hist_df[display_cols].copy()
        if "strike" in display_df.columns:
            # Keep display type consistent for Arrow when strike contains ints and CE/PE strings.
            display_df["strike"] = display_df["strike"].astype(str)
        st.dataframe(display_df, width='stretch', hide_index=True)

        # Delete a trade by ID
        with st.expander("Delete a trade (use carefully)"):
            trade_ids = [t["id"] for t in hist_trades if t.get("id")]
            selected_del_id = st.selectbox("Select Trade ID", options=trade_ids, key="del_trade_id_select")
            del_id = st.text_input("Or type Trade ID manually", key="del_trade_id_text").strip()
            target_id = del_id or selected_del_id
            st.caption("Trade ID format: YYYYMMDD_HHMMSS (example: 20260707_135220)")
            if st.button("Delete Trade", key="del_btn"):
                if target_id and tt.delete_trade(target_id):
                    st.success(f"Trade {target_id} deleted.")
                    st.rerun()
                else:
                    st.warning("Trade ID not found for current history view.")


# ============================================================
#  TAB 8 — Learn / Help
# ============================================================

with tab8:
    st.header("📚 Learn — Indian Markets & Options")
    st.caption("Short tutorials on the core concepts used in this application.")

    with st.expander("🔢 What is the Put-Call Ratio (PCR)?", expanded=True):
        st.markdown("""
### Put-Call Ratio (PCR)

**Definition:**
PCR = Total Put Open Interest / Total Call Open Interest

It measures whether market participants are buying more puts (bearish protection)
or more calls (bullish bets).

**How to read PCR (commonly used interpretation):**

| PCR Value | What it may indicate               | Contrarian interpretation         |
|-----------|------------------------------------|----------------------------------|
| > 1.5     | Extreme put buying (high fear)     | Potential oversold bounce        |
| 1.2–1.5   | Elevated put activity              | Mildly contrarian bullish        |
| 0.8–1.2   | Balanced / neutral                 | No strong signal                 |
| 0.5–0.8   | More call buying (optimism)        | Mildly contrarian bearish        |
| < 0.5     | Extreme call buying (complacency)  | Potential market top caution     |

**Important caveats:**
- PCR is a *lagging* indicator derived from settled positions.
- PCR does NOT predict market direction with certainty.
- In a strong trend, PCR can remain elevated/depressed for weeks.
- Always combine PCR with price action, trend, and other indicators.

**NSE context:**
NSE publishes option chain data daily. PCR for NIFTY and BANKNIFTY is widely
tracked by Indian traders. The weekly PCR on expiry days is considered most
significant.
        """)

    with st.expander("📋 Option Chain Basics"):
        st.markdown("""
### Reading an Option Chain

An option chain is a table showing all available calls (CE) and puts (PE) for a
given underlying, expiry, and strike range.

**Key columns:**

| Column    | What it means                                                            |
|-----------|--------------------------------------------------------------------------|
| Strike    | The price at which you can buy/sell the underlying at expiry.            |
| LTP       | Last Traded Price — the most recent option premium.                      |
| OI        | Open Interest — number of outstanding contracts at this strike.          |
| Volume    | Contracts traded today.                                                  |
| IV        | Implied Volatility — the market's expectation of future volatility.      |

**ATM / ITM / OTM:**
- **ATM** (At The Money): Strike ≈ Current spot price.
- **ITM** (In The Money): Call where Strike < Spot; Put where Strike > Spot. Has intrinsic value.
- **OTM** (Out of The Money): Call where Strike > Spot; Put where Strike < Spot. Only time value.

**Max Pain:**
The strike price where the total financial loss of all option buyers is maximised.
Option sellers theoretically benefit if the index expires at this price.
Max Pain is a *theory*, not a guaranteed outcome.

**IV Skew:**
Normally, OTM put options have higher IV than OTM call options in equity markets
(called "negative skew" or "put skew"). This reflects demand for downside protection.
        """)

    with st.expander("📦 Futures Basics"):
        st.markdown("""
### Futures Contracts on NSE

A **futures contract** is an agreement to buy or sell an underlying asset at a
predetermined price on a specified future date.

**Key features:**
- **Lot Size**: NIFTY = 65 units; BANKNIFTY = 15 units.
- **Expiry**: NSE futures expire on the last Thursday of each month.
- **Mark-to-Market (MTM)**: Daily profit and loss is settled every day — unlike options,
  you can receive or need to pay margin on a daily basis.
- **Leverage**: You only need to put up a margin (typically 10–15% of contract value),
  but your P&L is on the *full* contract value.

**OI & Volume signals:**

| Price | OI   | Interpretation                                |
|-------|------|-----------------------------------------------|
| Up    | Up   | Fresh long positions — strong bullish trend    |
| Up    | Down | Short covering — rally may be weak             |
| Down  | Up   | Fresh short positions — strong bearish trend   |
| Down  | Down | Long liquidation — mild weakness               |

**Roll-over:**
Near expiry, traders roll their futures position to the next month's contract.
High roll-over with stable price = participants are confident in the trend.

**Important**: Futures are leveraged instruments. A 1% adverse move on NIFTY
futures can result in a much larger loss relative to margin deposited.
        """)

    with st.expander("🧪 Backtesting — What It Is and What It Isn't"):
        st.markdown("""
### Introduction to Backtesting

**What is backtesting?**
Backtesting simulates running a trading strategy on *historical* data to see how
it *would have* performed if you had traded it in the past.

**Why backtest?**
- Understand if the strategy has a theoretical edge.
- Identify failure modes (what market conditions hurt the strategy?).
- Tune parameters (but be careful of overfitting!).

**Golden rules of backtesting:**

1. **Never use future data to generate past signals.** (Look-ahead bias)
2. **Always include realistic costs**: brokerage, STT, impact cost, slippage.
3. **Use out-of-sample validation**: Train on one period, test on another.
4. **Check multiple market regimes**: Trending, sideways, high/low volatility.
5. **Past performance ≠ future results.** Markets change; so do strategies.

**Common pitfalls:**
- **Overfitting**: Tuning 10 parameters to fit 2 years of data perfectly. The
  strategy is memorising noise, not learning a genuine edge.
- **Survivorship bias**: Only backtesting assets that exist today (winners).
- **Ignoring slippage**: Assuming fills at exactly the signal price.
- **Unrealistic trade size**: Assuming you can trade any size without market impact.

**This tool's limitations:**
All data is *synthetic* (generated by a mathematical model, NOT real NSE data).
This makes the backtest even less predictive. Use it purely to understand the
*mechanics* of the strategy, not to judge its real-world viability.
        """)

    with st.expander("⚡ Options Greeks — Quick Reference"):
        st.markdown("""
### The Four Main Greeks

| Greek  | Symbol | Measures                                    | Sign for Long Call |
|--------|--------|---------------------------------------------|--------------------|
| Delta  | δ      | Price change per ₹1 move in underlying      | +0 to +1           |
| Gamma  | Γ      | Delta change per ₹1 move in underlying      | Always positive    |
| Theta  | Θ      | Daily time decay (value lost per day)       | Negative           |
| Vega   | ν      | Value change per 1% change in IV            | Positive           |

**Delta**
- ATM options: delta ≈ ±0.5
- Deep ITM options: delta approaches ±1
- Deep OTM options: delta approaches 0

**Theta (Time Decay)**
- Options lose value every day (all else equal).
- Time decay *accelerates* in the last 2–3 weeks before expiry.
- Buyers lose theta; sellers gain it.

**Vega and IV**
- If implied volatility (IV) rises, all options become more expensive.
- IV tends to spike before major events (budget, RBI policy, earnings).
- After the event, IV often collapses ("IV crush") — harming option buyers.

**Practical example:**
You buy a NIFTY call with:
- Delta = 0.45 → NIFTY up ₹100 → your call gains ≈ ₹45
- Theta = −₹15 → You lose ≈ ₹15 per day just from time passing
- Vega  = ₹25  → IV up 1% → your call gains ≈ ₹25
        """)

    with st.expander("⚠️ Risk Disclaimer & Educational Purpose"):
        st.markdown("""
## ⚠️ Important Disclaimer

This application — **Indian Market Study Tool** — is built **SOLELY for educational
and research purposes**. Please read the following carefully:

1. **No financial advice**: Nothing in this application constitutes investment advice,
   a recommendation, or a solicitation to buy or sell any security, derivative, or
   financial instrument.

2. **Synthetic data**: All market data displayed is **artificially generated** using
   mathematical models. It does NOT represent actual NSE/BSE prices, and any
   resemblance to real market data is coincidental.

3. **No live trading**: This application does NOT connect to any brokerage,
   exchange API, or trading system. No real money is ever at risk.

4. **Hypothetical results**: All backtest results are hypothetical and based on
   synthetic data. They are NOT indicative of future performance.

5. **Options & futures risk**: Options and futures are complex, leveraged instruments.
   In real markets, you can lose more than your initial investment. Seek professional
   advice before trading derivatives.

6. **Consult a professional**: If you are considering investing in Indian markets,
   please consult a SEBI-registered investment advisor or portfolio manager.

7. **Regulatory note**: Trading in Indian derivatives requires a registered brokerage
   account, fulfillment of SEBI KYC requirements, and compliance with applicable laws.

---

*This tool is intended for students, researchers, and learners who want to understand
how quantitative analysis, options pricing, and backtesting work in the context of
Indian equity markets. It is not, and should not be used as, a trading system.*
        """)


# ============================================================
#  TAB 9 — Auto Trade Log
# ============================================================

with tab9:
    import json as _json
    from pathlib import Path as _Path
    from datetime import date as _date

    _AUTO_LOG = _Path("data/auto_trade_log.json")

    st.header("🤖 Auto Trade Log")
    st.caption(
        "Paper-trades automatically logged by the 10:15 morning cron run. "
        "Open positions update every hour. Closed at 15:30 with final P&L."
    )

    # ── Helper: Live option chain & position P&L update in pure Python ──
    def _trigger_live_pnl_update_py():
        """Scrapes the option chain data directly from niftytrader.in in pure Python
        and writes it as a JSON file, then converts it and updates open trade P&Ls.
        Matches PowerShell output structure exactly but avoids subprocess and OS dependencies.
        """
        import requests as _req
        import re as _re_p
        import json as _js_p
        from datetime import datetime as _dt_p, timezone as _tz_p
        from pathlib import Path as _Path_p
       
        _url = "https://www.niftytrader.in/nse-option-chain/nifty"
        _headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Referer": "https://www.google.com"
        }
       
        try:
            _r = _req.get(_url, headers=_headers, timeout=12)
            _r.raise_for_status()
           
            _nd = _re_p.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', _r.text)
            if not _nd:
                return False
               
            _nd_json = _js_p.loads(_nd.group(1))
            _pp = _nd_json.get("props", {}).get("pageProps", {})
            _spot = _pp.get("initialSpot", {})
            if not _spot:
                return False
               
            _out = {
                "symbol": "NIFTY",
                "timestamp": _spot.get("timestamp", ""),
                "cron_run_time": _dt_p.now(_tz_p.utc).isoformat(),
                "cron_run_label": _dt_p.now().strftime("%H:%M"),
                "source": "niftytrader.in (live, no-auth)",
                "source_url": _url,
                "spot_price": float(_spot.get("last_trade_price", 0) or 0),
                "open": float(_spot.get("open", 0) or 0),
                "high": float(_spot.get("high", 0) or 0),
                "low": float(_spot.get("low", 0) or 0),
                "vix": float(_spot.get("vix_value", 0) or 0),
                "vix_change": float(_spot.get("vix_change", 0) or 0),
                "max_pain": float(_spot.get("max_pain", 0) or 0),
                "lot_size": int(_spot.get("lot_size", 25) or 25),
                "expected_range": _pp.get("ExpectedRange", ""),
                "pcr": float(_pp.get("pcrVal", 0) or 0),
                "pcr_change": float(_pp.get("chngPcrValue", 0) or 0) if _pp.get("chngPcrValue") else None,
                "strikes": []
            }
           
            _raw_rows = _pp.get("initialOptionChainData", [])
            for _row in sorted(_raw_rows, key=lambda x: float(x.get("strike_price", 0) or 0)):
                _out["strikes"].append({
                    "strike": float(_row.get("strike_price", 0) or 0),
                    "expiry": _row.get("expiry_date", ""),
                    "pcr": float(_row.get("pcr", 0)) if _row.get("pcr") else None,
                    "CE": {
                        "oi": int(_row.get("calls_oi", 0) or 0),
                        "chg_oi": int(_row.get("calls_change_oi", 0) or 0),
                        "ltp": float(_row.get("calls_ltp", 0) or 0),
                        "iv": float(_row.get("calls_iv", 0) or 0),
                        "volume": int(_row.get("calls_volume", 0) or 0),
                        "buildup": _row.get("calls_builtup", "")
                    },
                    "PE": {
                        "oi": int(_row.get("puts_oi", 0) or 0),
                        "chg_oi": int(_row.get("puts_change_oi", 0) or 0),
                        "ltp": float(_row.get("puts_ltp", 0) or 0),
                        "iv": float(_row.get("puts_iv", 0) or 0),
                        "volume": int(_row.get("puts_volume", 0) or 0),
                        "buildup": _row.get("puts_builtup", "")
                    }
                })
               
            _date_stamp = _dt_p.now().strftime("%Y%m%d")
            _Path_p("downloads").mkdir(exist_ok=True)
            _Path_p(f"downloads/option_chain_NIFTY_{_date_stamp}.json").write_text(_js_p.dumps(_out, indent=2), encoding="utf-8")
            _Path_p(f"downloads/pcr_NIFTY_{_date_stamp}.json").write_text(_js_p.dumps({"pcr_overall": _out["pcr"], "timestamp": _out["timestamp"]}, indent=2), encoding="utf-8")
           
            # Run CSV conversion dynamically
            import convert_cron_to_app
            import importlib
            importlib.reload(convert_cron_to_app)
            convert_cron_to_app.main()
           
            # Run trade engine updater dynamically
            from src.auto_trade_engine import update_open_trades
            update_open_trades(mode="update")
            return True
        except Exception as _e:
            import logging
            logging.getLogger("market_study_tool").error(f"Live updater error: {_e}")
            return False

    def _upgrade_old_condor_rows(log_rows: list[dict]) -> tuple[list[dict], int, int]:
        """Backfill missing iron condor wing/short leg fields for historical rows.

        Heuristic:
        - Parse short CE/PE from strike text when available.
        - Estimate wing width from stored margin per lot (investment_amount / lot_size),
          rounded to nearest strike interval (50).
        - Fall back to 200-point wings if margin-based estimate is unavailable.
        """
        import re as _re

        updated = 0
        skipped = 0
        out = []

        for row in log_rows:
            r = dict(row)
            inst = str(r.get("instrument", "")).lower()
            if "iron condor" not in inst:
                out.append(r)
                continue

            has_all = bool(r.get("short_ce_strike") and r.get("short_pe_strike") and r.get("buy_ce_strike") and r.get("buy_pe_strike"))
            if has_all:
                out.append(r)
                skipped += 1
                continue

            strike_text = str(r.get("strike", ""))
            short_ce = r.get("short_ce_strike")
            short_pe = r.get("short_pe_strike")

            if (not short_ce or not short_pe) and "/" in strike_text:
                parts = [p.strip() for p in strike_text.split("/")]
                for p in parts:
                    nums = _re.findall(r"\d+", p)
                    if not nums:
                        continue
                    strike_num = int(nums[0])
                    if "CE" in p and not short_ce:
                        short_ce = strike_num
                    if "PE" in p and not short_pe:
                        short_pe = strike_num

            if not short_ce or not short_pe:
                out.append(r)
                skipped += 1
                continue

            lot_sz = int(r.get("lot_size", 25) or 25)
            invest = float(r.get("investment_amount", 0) or 0)
            width_est = 0
            if lot_sz > 0 and invest > 0:
                # For condor rows, investment_amount is approx spread_width * lot_size.
                width_est = int(round((invest / lot_sz) / 50.0) * 50)
            if width_est <= 0:
                width_est = 200
            width_est = max(50, width_est)

            r["short_ce_strike"] = int(short_ce)
            r["short_pe_strike"] = int(short_pe)
            r["buy_ce_strike"] = int(short_ce) + int(width_est)
            r["buy_pe_strike"] = int(short_pe) - int(width_est)
            r["wing_inferred"] = True
            r["wing_inference_method"] = "margin_width_heuristic" if invest > 0 else "default_200"

            out.append(r)
            updated += 1

        return out, updated, skipped

    def _migrate_open_nifty_lot_size(
        log_rows: list[dict],
        from_lot: int = 25,
        to_lot: int = 65) -> tuple[list[dict], int, int]:
        """Migrate open NIFTY rows from one lot_size to another.

        Updates lot_size and rescales investment/current P&L fields so UI metrics remain consistent.
        Closed/skipped rows are intentionally left unchanged.
        """
        if from_lot <= 0 or to_lot <= 0 or from_lot == to_lot:
            return log_rows, 0, len(log_rows)

        out = []
        updated = 0
        skipped = 0
        ratio = float(to_lot) / float(from_lot)

        for row in log_rows:
            r = dict(row)
            is_nifty = str(r.get("symbol", "")).upper() == "NIFTY"
            is_open = str(r.get("status", "")) == "Open"
            row_lot = int(r.get("lot_size", 0) or 0)

            if not (is_nifty and is_open and row_lot == from_lot):
                out.append(r)
                skipped += 1
                continue

            r["lot_size"] = int(to_lot)

            # Keep capital denominator aligned with new lot size.
            invest = float(r.get("investment_amount", 0) or 0)
            if invest > 0:
                r["investment_amount"] = round(invest * ratio, 2)

            # Recompute live P&L using current mark, direction, and new lot_size.
            try:
                entry = float(r.get("entry_price", 0) or 0)
                curr = float(r.get("current_ltp", entry) or entry)
                qty = int(r.get("qty_lots", 1) or 1)
                direct = str(r.get("direction", "buy")).lower()
                if "sell" in direct:
                    pnl = (entry - curr) * to_lot * qty
                else:
                    pnl = (curr - entry) * to_lot * qty
                r["current_pnl"] = round(pnl, 2)

                inv_now = float(r.get("investment_amount", 0) or 0)
                r["current_pnl_pct"] = round((pnl / inv_now) * 100, 2) if inv_now > 0 else 0.0
            except Exception:
                # If recomputation fails, at least keep proportional scaling.
                cp = float(r.get("current_pnl", 0) or 0)
                r["current_pnl"] = round(cp * ratio, 2)

            r["lot_migrated"] = True
            r["lot_migration_note"] = f"Open NIFTY migrated {from_lot}->{to_lot}"
            updated += 1
            out.append(r)

        return out, updated, skipped

    # ── Real-time Value Streaming Toggle ──────────────────────
    _col_stream1, _col_stream2 = st.columns([3, 1])
    with _col_stream1:
        _stream_val = st.toggle("🔌 Active Live Streaming (Fetch new quotes & updates P&L every 10s)", value=False, key="at_live_streaming_toggle")
   
    if _stream_val:
        # Trigger pure Python live update silently without manual button force reloads!
        with st.spinner("Streaming live quotes..."):
            _trigger_live_pnl_update_py()
        # Sleep 10s then rerun automatically
        import time as _time
        _time.sleep(10)
        st.rerun()

    # ── Prominent action buttons at top ──────────────────────
    _tb1, _tb2, _tb3, _tb4 = st.columns(4)
    if _tb1.button("🔄 Refresh Data + P&L", key="at_refresh_btn", type="primary", help="Download latest option chain prices then refresh open P&L"):
        with st.spinner("Downloading and parsing fresh option prices (in pure Python)..."):
            if _trigger_live_pnl_update_py():
                st.toast("Real-time option chain & position P&L updated!", icon="✅")
            else:
                st.error("Failed to fetch live option chain data.")
        st.rerun()

    if _tb2.button("▶ New Trade Entry", key="at_entry_btn", type="primary", help="Log today's 4 auto-trades now (same as 10:15 cron)"):
        import subprocess as _sp
        with st.spinner("Logging trades..."):
            _r = _sp.run(["python", "src/auto_trade_engine.py", "--mode=entry"],
                         capture_output=True, text=True, cwd=str(_Path(".").resolve()))
        st.code((_r.stdout + _r.stderr)[:1200])
        st.rerun()

    if _tb3.button("🔒 Close All Open", key="at_eod_btn", help="Close all open positions with current prices (EOD)"):
        import subprocess as _sp
        with st.spinner("Closing positions..."):
            _r = _sp.run(["python", "src/auto_trade_engine.py", "--mode=eod"],
                         capture_output=True, text=True, cwd=str(_Path(".").resolve()))
        st.toast("Positions closed!", icon="🔒")
        st.rerun()

    if _tb4.button("🗑️ Clear All Logs", key="at_clear_btn", help="Delete entire auto trade log (irreversible)"):
        if st.session_state.get("_at_confirm_clear"):
            _AUTO_LOG.write_text("[]", encoding="utf-8")
            st.session_state["_at_confirm_clear"] = False
            st.toast("All logs cleared.", icon="🗑️")
            st.rerun()
        else:
            st.session_state["_at_confirm_clear"] = True
            st.warning("⚠️ Click **🗑️ Clear All Logs** again to confirm. This cannot be undone.")

    # ── Advanced controls (collapsible) ──────────────────────
    with st.expander("⚙️ Advanced Controls", expanded=False):
        st.caption("Additional cron controls.")
        _mc1, _mc2, _mc3, _mc4 = st.columns(4)
        if _mc1.button("🧩 Upgrade Old Condors", key="at_upgrade_condors_btn"):
            try:
                _raw = []
                if _AUTO_LOG.exists():
                    _raw = _json.loads(_AUTO_LOG.read_text(encoding="utf-8"))
                _upgraded, _u_count, _s_count = _upgrade_old_condor_rows(_raw)
                _AUTO_LOG.write_text(_json.dumps(_upgraded, indent=2, default=str), encoding="utf-8")
                st.success(f"Upgraded {_u_count} condor row(s); {_s_count} already complete/unchanged.")
                st.rerun()
            except Exception as _e_upg:
                st.error(f"Could not upgrade old condor rows: {_e_upg}")
        if _mc2.button("🔄 Update P&L only", key="at_update_btn"):
            import subprocess as _sp
            _r = _sp.run(["python", "src/auto_trade_engine.py", "--mode=update"],
                         capture_output=True, text=True, cwd=str(_Path(".").resolve()))
            st.code((_r.stdout + _r.stderr)[:2000])
            st.rerun()
        if _mc3.button("📥 Full Cron Download", key="at_full_cron_btn"):
            import subprocess as _sp
            import platform as _pl
            with st.spinner("Running full cron (may take ~60s)..."):
                if _pl.system() == "Windows":
                    _r = _sp.run(
                        ["powershell", "-ExecutionPolicy", "Bypass", "-File",
                         str(_Path(".").resolve() / "download_nse_data.ps1"), "-Mode", "auto"],
                        capture_output=True, text=True, cwd=str(_Path(".").resolve()))
                else:
                    _r = _sp.run(["python", "download_nse_data.py"], capture_output=True, text=True, cwd=str(_Path(".").resolve()))
            st.code(_r.stdout[:2000])
            st.rerun()
        if _mc4.button("🧮 Migrate Open NIFTY 25→65", key="at_migrate_nifty_lot_btn"):
            try:
                _raw = []
                if _AUTO_LOG.exists():
                    _raw = _json.loads(_AUTO_LOG.read_text(encoding="utf-8"))
                _migrated, _m_count, _s_count = _migrate_open_nifty_lot_size(_raw, from_lot=25, to_lot=65)
                _AUTO_LOG.write_text(_json.dumps(_migrated, indent=2, default=str), encoding="utf-8")
                st.success(f"Migrated {_m_count} open NIFTY row(s) from lot 25 to 65; {_s_count} unchanged.")
                st.rerun()
            except Exception as _e_mig:
                st.error(f"Could not migrate open NIFTY lot size: {_e_mig}")

    st.divider()

    # ── Helper: Analyze trade from microstructure perspective ──
    def _analyze_trade_winner(trade, symbol):
        """Determine likely winner (crowd vs smart money) based on microstructure.
       
        Uses market microstructure analysis if option chain data is current,
        otherwise falls back to simple rules based on direction and instrument type.
        """
        try:
            import re
           
            # Get trade info
            _trade_symbol = trade.get("symbol", symbol)
            _trade_strike_str = str(trade.get("strike", "")).strip()
            _direction = str(trade.get("direction", "")).lower().strip()
            _instrument = str(trade.get("instrument", "")).lower().strip()
           
            if not _trade_strike_str or _trade_strike_str == "" or _trade_strike_str == "—":
                return "—"
           
            # Parse strikes
            _strikes_nums = re.findall(r'\d+', _trade_strike_str)
            _trade_strikes_set = set()
           
            for _s in _strikes_nums:
                try:
                    _strike_int = int(_s)
                    if 1000 <= _strike_int <= 100000:
                        _trade_strikes_set.add(_strike_int)
                except:
                    pass
           
            if not _trade_strikes_set:
                return "—"
           
            # ── FALLBACK LOGIC — sentiment-aware buyer classification ──
            # Import the fixed winner_label that uses sentiment context
            try:
                from src.strategy_selector import winner_label as _wl_fn
                _sent_score = int(trade.get("sentiment_score", 0) or 0)
                return _wl_fn(_direction, _instrument, _sent_score)
            except Exception:
                pass
            if "buy" in _direction or ("ce" in _instrument and "sell" not in _direction):
                # Buyers typically lose in crowded trades
                if "spread" not in _instrument:
                    return "👥 Crowd (Lose)"
                else:
                    # Spreads are structured, less likely to lose
                    return "🧠 Smart (Win)"
            elif "sell" in _direction or "spread" in _instrument:
                # Sellers with defined risk (spreads) typically win
                return "🧠 Smart (Win)"
            else:
                return "—"
               
        except Exception as _e_mm:
            return "—"

    # ── Helper: Analyze hold/exit decision based on market direction ──
    def _analyze_hold_exit(trade, symbol):
        """Determine if trade should HOLD or EXIT based on market movement vs thesis.
       
        Returns: (emoji_icon, decision, justification_text)
        """
        try:
            _ep = float(trade.get("entry_price", 0) or 0)
            _cur = float(trade.get("current_ltp", _ep) or _ep)
            _pnl = float(trade.get("current_pnl", 0) or 0)
            _dir = str(trade.get("direction", "buy")).lower().strip()
            _status = str(trade.get("status", "Open")).lower()
           
            # Skip closed/skipped trades
            if _status != "open":
                return "—", "—", "—"
           
            if _ep <= 0 or _cur <= 0:
                return "⚪", "Hold", "Insufficient data"
           
            # Determine market movement direction
            _moved_up = _cur > _ep
            _is_profitable = _pnl >= 0
           
            # For BUY trades (expecting upside)
            if "buy" in _dir or "long" in _dir:
                if _moved_up and _is_profitable:
                    return "🟢", "HOLD", "Market up + Profit ✓ Thesis working, stay"
                elif _moved_up and not _is_profitable:
                    return "🟡", "REASSESS", "Market up but Loss ✗ Wrong entry level, consider exit"
                elif not _moved_up and _is_profitable:
                    return "🟢", "HOLD", "Market down yet Profitable ✓ Unusual but good, hold SL"
                else:  # not moved up and not profitable
                    return "🔴", "EXIT", "Market down + Loss ✗ Thesis broken, exit now"
           
            # For SELL trades (expecting downside)
            elif "sell" in _dir or "short" in _dir:
                if not _moved_up and _is_profitable:
                    return "🟢", "HOLD", "Market down + Profit ✓ Thesis working, stay"
                elif not _moved_up and not _is_profitable:
                    return "🟡", "REASSESS", "Market down but Loss ✗ Wrong entry level, consider exit"
                elif _moved_up and _is_profitable:
                    return "🟢", "HOLD", "Market up yet Profitable ✓ Unusual but good, hold SL"
                else:  # moved up and not profitable
                    return "🔴", "EXIT", "Market up + Loss ✗ Thesis broken, exit now"
           
            return "⚪", "Hold", "Direction unclear"
           
        except Exception as _e_hx:
            return "⚪", "—", "—"

    # ── load log ─────────────────────────────────────────────
    _at_all = []
    if _AUTO_LOG.exists():
        try:
            _at_all = _json.loads(_AUTO_LOG.read_text(encoding="utf-8"))
        except Exception as _e:
            st.error(f"Could not read auto_trade_log.json: {_e}")

    if not _at_all:
        st.info(
            "**No auto-trades logged yet.**\n\n"
            "The engine runs automatically at **10:15** on trading days (2nd cron run).\n\n"
            "Click **▶ Log Today's Trades** above to run it now manually."
        )
    else:
        _today_str = _date.today().isoformat()

        # ── Filters ──────────────────────────────────────────
        _fc1, _fc2, _fc3 = st.columns(3)
        _all_dates = sorted({t.get("date", "") for t in _at_all if t.get("date")}, reverse=True)
        _date_options = ["All dates"] + _all_dates
        # Default to today's date if available, otherwise "All dates"
        _default_date_idx = (_date_options.index(_today_str)
                             if _today_str in _date_options else 0)
        _sel_date  = _fc1.selectbox("Date", _date_options, index=_default_date_idx, key="at_date")
        _sel_strat = _fc2.selectbox(
            "Strategy",
            ["All", "Institutional", "OptionSeller", "OptionBuyer", "Hedging", "Agent-Institutional", "Agent-OptionSeller"],
            key="at_strat")
        _sel_status = _fc3.selectbox(
            "Status",
            ["All", "Open", "Closed", "SL_Hit", "Target_Hit", "Skipped"],
            key="at_status")

        _filtered = [
            t for t in _at_all
            if (_sel_date  == "All dates" or t.get("date")          == _sel_date)
            and (_sel_strat == "All"       or t.get("strategy_type") == _sel_strat)
            and (_sel_status == "All"      or t.get("status")        == _sel_status)
        ]

        # ── KPI row ───────────────────────────────────────────
        _open_cnt   = sum(1 for t in _filtered if t.get("status") == "Open")
        _closed_cnt = sum(1 for t in _filtered if t.get("status") not in ("Open", "Skipped"))
        _tot_invest = sum(float(t.get("investment_amount", 0) or 0)
                          for t in _filtered if t.get("status") != "Skipped")
        _tot_pnl    = sum(float(t.get("pnl_amount", 0) or 0)
                          for t in _filtered if t.get("pnl_amount") is not None)
        _live_pnl   = sum(float(t.get("current_pnl", 0) or 0)
                          for t in _filtered if t.get("status") == "Open")
        _winners    = sum(1 for t in _filtered if (t.get("pnl_amount") or 0) > 0)
        _win_rate   = f"{_winners / _closed_cnt * 100:.0f}%" if _closed_cnt else "N/A"
        _total_pnl_all = _tot_pnl + _live_pnl

        _k1, _k2, _k3, _k4, _k5, _k6, _k7 = st.columns(7)
        _k1.metric("Open",         _open_cnt,
                   help="Positions still active today — not yet closed or expired.")
        _k2.metric("Closed",       _closed_cnt,
                   help="Positions closed (EOD, SL Hit, or Target Hit).")
        _k3.metric("Win Rate",     _win_rate,
                   help="% of closed trades that made a profit.")
        _k4.metric("Invested ₹",   f"{_tot_invest:,.0f}",
                   help="Total capital deployed across all filtered trades (premium + SPAN margin).")
        _k5.metric("Realised P&L", f"₹{_tot_pnl:,.0f}", delta=f"{_tot_pnl:+.0f}",
                   help="Final P&L on closed trades only (SL Hit, Target Hit, or EOD Close).")
        _k6.metric("Live P&L",     f"₹{_live_pnl:,.0f}", delta=f"{_live_pnl:+.0f}",
                   help="Unrealised P&L on open positions using current LTP. Updates each cron run.")
        _k7.metric("Total P&L",    f"₹{_total_pnl_all:,.0f}", delta=f"{_total_pnl_all:+.0f}",
                   help="Realised + Unrealised P&L combined.")

        # ---- Timestamps row ----
        try:
            _last_update_t = max(
                (t.get("last_updated", "") for t in _at_all if t.get("last_updated")),
                default="—")
            _last_entry_d = max(
                (t.get("date", "") for t in _at_all), default="—"
            )
            import glob as _g2, json as _js3
            _oc3 = sorted(
                _g2.glob(str(_Path(".").resolve() / "downloads" / "option_chain_*.json")),
                key=lambda p: _Path(p).stat().st_mtime, reverse=True)
            _data_cron = "—"
            if _oc3:
                _raw3 = _js3.loads(_Path(_oc3[0]).read_bytes().decode("utf-8-sig"))
                _data_cron = (_raw3.get("cron_run_time", "") or _raw3.get("timestamp", "") or "")[:16] or "—"
            _tc1, _tc2, _tc3 = st.columns(3)
            _tc1.info(f"📅 **Last trade entry**  \n`{_last_entry_d}`")
            _tc2.info(f"🔄 **Last P&L update**  \n`{_last_update_t}`")
            _tc3.info(f"📡 **Last data download**  \n`{_data_cron}`")
        except Exception:
            pass

        st.divider()

        # ── Today's in-progress positions ────────────────────
        _today_open = [t for t in _at_all
                       if t.get("date") == _today_str and t.get("status") == "Open"]
        if _today_open:
            st.subheader(f"🔴 In-Progress Today — {_today_str}")
            for _t in _today_open:
                _entry  = float(_t.get("entry_price",   0) or 0)
                _cur    = float(_t.get("current_ltp",   _entry) or _entry)
                _cpnl   = float(_t.get("current_pnl",   0) or 0)
                _cpct   = float(_t.get("current_pnl_pct", 0) or 0)
                _invest = float(_t.get("investment_amount", 0) or 0)
                _stype  = _t.get("strategy_type", "")
                _icon   = {"Institutional": "🏦", "OptionSeller": "⚙️",
                           "OptionBuyer": "🛒", "Hedging": "🛡️"}.get(_stype, "📊")

                with st.container(border=True):
                    _a, _b, _c, _d, _e, _f = st.columns([2, 2, 2, 2, 2, 3])
                    _a.metric(f"{_icon} {_stype}", str(_t.get("instrument", "")),
                              help=f"Strategy: {_stype} | Direction: {_t.get('direction','')}")
                    _b.metric("Strike", str(_t.get("strike", "")),
                              help="Strike price. For spreads: CE:sell/PE:sell format.")
                    _c.metric("Entry ₹", f"₹{_entry:,.2f}",
                              help="Premium paid/received at entry per unit.")
                    _d.metric("Current ₹", f"₹{_cur:,.2f}",
                              help="Latest option LTP. Refreshes every hourly cron.")
                    _e.metric("Live P&L", f"₹{_cpnl:,.0f}", delta=f"{_cpct:+.2f}%",
                              help=f"SL ₹{float(_t.get('stop_loss',0)):,.2f}  |  Target ₹{float(_t.get('target',0)):,.2f}")
                    _f.metric("Invested ₹", f"₹{_invest:,.0f}",
                              help="Premium (buyers) or SPAN margin (sellers) for 1 lot.")
                    with st.expander("Details"):
                        _d1, _d2, _d3 = st.columns(3)
                        _d1.markdown(f"**SL:** ₹{float(_t.get('stop_loss',0)):.2f}  \n**Target:** ₹{float(_t.get('target',0)):.2f}")
                        _d2.markdown(f"**PCR:** {float(_t.get('pcr',0)):.4f}  \n**VIX:** {float(_t.get('vix',0)):.2f}")
                        _d3.markdown(f"**Sentiment:** {_t.get('sentiment_label','')}  \n**Regime:** {_t.get('regime','')}")
                        if _t.get("validation_flags"):
                            st.caption(f"Flags: {_t['validation_flags']}")
                        if _t.get("reason"):
                            st.caption(_t["reason"][:200])
            st.divider()

        # ── Full trades table ─────────────────────────────────
        st.subheader("All Trades")

        _STATUS_ICON = {
            "Open":       "🔵", "Closed":     "⚫",
            "SL_Hit":     "🔴", "Target_Hit": "🟢", "Skipped": "⬜",
        }
        _STRAT_ICON = {
            "Institutional": "🏦", "OptionSeller": "⚙️",
            "OptionBuyer": "🛒", "Hedging": "🛡️",
            "Agent-Institutional": "🤖🏦", "Agent-OptionSeller": "🤖⚙️",
        }

        _rows = []
        for _t in sorted(_filtered,
                          key=lambda x: (x.get("date", ""), x.get("entry_time", "")),
                          reverse=True):
            _invest  = float(_t.get("investment_amount", 0) or 0)
            _status  = _t.get("status", "Open")
            _live    = _status == "Open"
            _pnl_a   = _t.get("pnl_amount")
            _pnl_p   = _t.get("pnl_pct")
            _disp_pnl = float(_t.get("current_pnl", 0) or 0) if _live else float(_pnl_a or 0)
            _disp_pct = float(_t.get("current_pnl_pct", 0) or 0) if _live else float(_pnl_p or 0)
            _stype   = _t.get("strategy_type", "")
            _ep      = float(_t.get("entry_price", 0) or 0)
            _sl      = float(_t.get("stop_loss",   0) or 0)
            _tgt     = float(_t.get("target",      0) or 0)
            _exit    = float(_t.get("exit_price",  0) or 0) if _t.get("exit_price") else None
            _expiry  = str(_t.get("expiry", "") or "").strip()
            _pnl_sign = "+" if _disp_pnl >= 0 else "-"
            _pct_sign = "+" if _disp_pct >= 0 else "-"

            # Display 4-leg structure for condor rows when wing metadata is available.
            _raw_strike = str(_t.get("strike", ""))
            _strike_disp = _raw_strike
            _instr_l = str(_t.get("instrument", "")).lower()
            _stype_l = str(_t.get("strategy_type", "")).lower()
            _is_seller = ("optionseller" in _stype_l) or ("agent-optionseller" in _stype_l)
            _is_condor = "iron condor" in _instr_l
            if _is_seller and _is_condor:
                _s_ce = _t.get("short_ce_strike")
                _s_pe = _t.get("short_pe_strike")
                _b_ce = _t.get("buy_ce_strike")
                _b_pe = _t.get("buy_pe_strike")
                if _s_ce and _s_pe and _b_ce and _b_pe:
                    _strike_disp = f"PE:B{_b_pe}/S{_s_pe} | CE:S{_s_ce}/B{_b_ce}"
                elif _s_ce and _s_pe:
                    _strike_disp = f"PE:S{_s_pe} | CE:S{_s_ce} (wings missing)"
           
            # Analyze who wins from microstructure perspective
            _likely_winner = _analyze_trade_winner(_t, symbol)
           
            # Analyze hold/exit decision based on market movement
            _decision_icon, _decision_text, _decision_reason = _analyze_hold_exit(_t, symbol)

            _rows.append({
                "Trade ID":   str(_t.get("id", "")),
                "Date":       _t.get("date", ""),
                "Time":       _t.get("entry_time", ""),
                "Strategy":   _STRAT_ICON.get(_stype, "📊") + " " + _stype,
                "Instrument": str(_t.get("instrument", "")),
                "Strike":     _strike_disp,
                "Expiry":     _expiry if _expiry else "—",
                "Entry ₹":    f"₹{_ep:,.2f}",
                "SL ₹":       f"₹{_sl:,.2f}",
                "Target ₹":   f"₹{_tgt:,.2f}",
                "Exit ₹":     f"₹{_exit:,.2f}" if _exit is not None else "—",
                "Invested ₹": f"₹{_invest:,.0f}",
                "P&L ₹":      f"{_pnl_sign}₹{abs(_disp_pnl):,.0f}",
                "P&L %":      f"{_pct_sign}{abs(_disp_pct):.2f}%",
                "Likely Winner": _likely_winner,
                "Hold/Exit":   _decision_icon + " " + _decision_text,
                "Reason":     _decision_reason,
                "Status":     _STATUS_ICON.get(_status, "⚪") + " " + _status,
                "VIX":        f"{float(_t.get('vix', 0) or 0):.2f}",
                "PCR":        f"{float(_t.get('pcr', 0) or 0):.4f}",
                "Sentiment":  _t.get("sentiment_label", ""),
                "Skip/Flag":  _t.get("skip_reason") or "",
                "Capital Model": _capital_model_label(_t),
                "Broker Margin Note": _broker_margin_note(_t),
                "Wing Source": (
                    "N/A" if "iron condor" not in str(_t.get("instrument", "")).lower()
                    else ("Inferred" if bool(_t.get("wing_inferred", False)) else (
                        "Exact" if all([
                            _t.get("short_ce_strike"), _t.get("short_pe_strike"),
                            _t.get("buy_ce_strike"), _t.get("buy_pe_strike")
                        ]) else "Missing"
                    ))
                ),
                "Groww Guide": "📋 Copy guide below",
            })

        if _rows:
            _df_at = pd.DataFrame(_rows)

            def _colour_pnl_text(val):
                if isinstance(val, str):
                    if val.startswith("+"):
                        return "color: green; font-weight: bold"
                    elif val.startswith("-"):
                        return "color: red; font-weight: bold"
                return ""

            def _highlight_open_row(row):
                """Green background for Open (live) trades; transparent for all others."""
                status_val = str(row.get("Status", ""))
                if "Open" in status_val:
                    return ["background-color: #d4edda; color: #155724"] * len(row)
                return [""] * len(row)

            st.dataframe(
                _df_at.style
                    .apply(_highlight_open_row, axis=1)
                    .map(_colour_pnl_text, subset=["P&L ₹", "P&L %"]),
                hide_index=True, height=min(80 + len(_rows) * 38, 650),
                column_config={
                    "Trade ID":    st.column_config.TextColumn("Trade ID", width=185,
                                       help="Unique logged trade identifier"),
                    "Date":        st.column_config.TextColumn("Date", width=95,
                                       help="Trade entry date (YYYY-MM-DD)"),
                    "Time":        st.column_config.TextColumn("Time", width=55,
                                       help="Time trade was logged (HH:MM)"),
                    "Strategy":    st.column_config.TextColumn("Strategy", width=170,
                                       help="Auto-trade strategy type"),
                    "Instrument":  st.column_config.TextColumn("Instrument / Strikes", width=200,
                                       help="Option type, strike and expiry. Hover for full text."),
                    "Strike":      st.column_config.TextColumn("Strike", width=130,
                                       help="Strike summary. For Iron Condor, shows 4 legs as PE:B/S and CE:S/B when available."),
                    "Expiry":      st.column_config.TextColumn("Expiry", width=95,
                                       help="Option expiry date for the trade"),
                    "Entry ₹":     st.column_config.TextColumn("Entry ₹", width=90,
                                       help="Option premium paid/received at entry (₹ per unit)"),
                    "SL ₹":        st.column_config.TextColumn("Stop-Loss ₹", width=90,
                                       help="Stop-loss price. Exit if premium hits this level."),
                    "Target ₹":    st.column_config.TextColumn("Target ₹", width=90,
                                       help="Target price. Take profit at this premium level."),
                    "Exit ₹":      st.column_config.TextColumn("Exit ₹", width=85,
                                       help="Actual exit price. — if still open."),
                    "Invested ₹":  st.column_config.TextColumn("Invested ₹", width=110,
                                       help="Capital deployed: premium × lot_size (buyers) or SPAN margin (sellers)"),
                    "P&L ₹":       st.column_config.TextColumn("P&L ₹", width=100,
                                       help="Profit / Loss in ₹. Green=profit, Red=loss. Live P&L shown for open trades."),
                    "P&L %":       st.column_config.TextColumn("P&L %", width=80,
                                       help="P&L as % of invested capital"),
                    "Likely Winner": st.column_config.TextColumn("Winner", width=130,
                                       help="👥 Crowd (Lose) = retail traders | 🧠 Smart (Win) = professional traders"),
                    "Hold/Exit":   st.column_config.TextColumn("Hold/Exit", width=140,
                                       help="🟢 HOLD = Thesis working | 🟡 REASSESS = Wrong entry | 🔴 EXIT = Thesis broken"),
                    "Reason":      st.column_config.TextColumn("Justification", width=220,
                                       help="Why to hold or exit based on market movement vs thesis"),
                    "Status":      st.column_config.TextColumn("Status", width=115,
                                       help="🔵 Open | ⚫ Closed (EOD) | 🟢 Target Hit | 🔴 SL Hit | ⬜ Skipped"),
                    "VIX":         st.column_config.TextColumn("VIX", width=55,
                                       help="India VIX at time of entry. >20 = high volatility."),
                    "PCR":         st.column_config.TextColumn("PCR", width=65,
                                       help="Put-Call Ratio at entry. >1.2 bullish, <0.8 bearish."),
                    "Sentiment":   st.column_config.TextColumn("Sentiment", width=145,
                                       help="Market sentiment label at entry time"),
                    "Skip/Flag":   st.column_config.TextColumn("Skip / Flag", width=130,
                                       help="Why trade was skipped, or validation flags (e.g. STALE_DATA, HOLIDAY)"),
                    "Capital Model": st.column_config.TextColumn("Capital Model", width=190,
                                       help="How Invested ₹ is computed in app (educational proxy vs premium-paid)."),
                    "Broker Margin Note": st.column_config.TextColumn("Broker Margin Note", width=260,
                                       help="Broker/exchange margin can differ from app proxy; verify before order."),
                    "Wing Source": st.column_config.TextColumn("Wing Source", width=95,
                                       help="For Iron Condor: Exact = logged legs, Inferred = upgraded heuristic, Missing = wings unavailable"),
                    "Groww Guide": st.column_config.TextColumn("Groww Guide", width=140,
                                       help="Use one-click copy buttons below to copy full step-by-step guide"),
                })

            st.markdown("### 📋 Groww Copy Buttons (One-click)")
            st.caption("Each button copies a complete step-by-step Groww guide for that specific trade.")
            _guide_source = sorted(
                _filtered,
                key=lambda x: (x.get("date", ""), x.get("entry_time", "")),
                reverse=True)
            for _tg in _guide_source:
                _gid = str(_tg.get("id", ""))
                _gstrategy = str(_tg.get("strategy_type", ""))
                _ginst = str(_tg.get("instrument", ""))
                _gstatus = str(_tg.get("status", "Open"))
                _gwing = (
                    "N/A" if "iron condor" not in _ginst.lower()
                    else ("Inferred" if bool(_tg.get("wing_inferred", False)) else (
                        "Exact" if all([
                            _tg.get("short_ce_strike"), _tg.get("short_pe_strike"),
                            _tg.get("buy_ce_strike"), _tg.get("buy_pe_strike")
                        ]) else "Missing"
                    ))
                )
                _gline = f"{_gid} | {_gstrategy} | {_ginst} | {_gstatus} | Wing: {_gwing}"
                _gc1, _gc2 = st.columns([4, 2])
                _gc1.markdown(f"**{_gline}**")
                with _gc2:
                    _guide_text = _build_groww_guide_from_trade(_tg)
                    _render_copy_button_html(
                        _guide_text,
                        label="📋 Copy Groww Guide",
                        key_suffix=f"{_gid}_{_tg.get('entry_time', '')}")
        else:
            st.info("No trades match the current filter.")

        st.divider()

        # ── Strategy performance summary ──────────────────────
        st.subheader("Strategy Performance Summary")
        _perf = []
        for _stype in ["Institutional", "OptionSeller", "OptionBuyer", "Hedging", "Agent-Institutional", "Agent-OptionSeller"]:
            _ts     = [t for t in _at_all if t.get("strategy_type") == _stype
                       and t.get("status") != "Skipped"]
            if not _ts:
                continue
            _closed_s = [t for t in _ts if t.get("pnl_amount") is not None]
            _inv_s    = sum(float(t.get("investment_amount", 0) or 0) for t in _ts)
            _pnl_s    = sum(float(t.get("pnl_amount", 0) or 0) for t in _closed_s)
            _live_s   = sum(float(t.get("current_pnl", 0) or 0)
                            for t in _ts if t.get("status") == "Open")
            _wins_s   = sum(1 for t in _closed_s if (t.get("pnl_amount") or 0) > 0)
            _sl_hits  = sum(1 for t in _closed_s if t.get("exit_trigger") == "SL_Hit")
            _tgt_hits = sum(1 for t in _closed_s if t.get("exit_trigger") == "Target_Hit")
            _icon = _STRAT_ICON.get(_stype, "📊")
            _perf.append({
                "Strategy":      f"{_icon} {_stype}",
                "#Trades":        len(_ts),
                "Open":          sum(1 for t in _ts if t.get("status") == "Open"),
                "Win Rate":      f"{_wins_s / len(_closed_s) * 100:.0f}%" if _closed_s else "—",
                "SL Hits":       _sl_hits,
                "Target Hits":   _tgt_hits,
                "Invested ₹":    f"{_inv_s:,.0f}",
                "Realised P&L":  f"₹{_pnl_s:,.0f}",
                "Live P&L":      f"₹{_live_s:,.0f}",
                "Total P&L":     f"₹{_pnl_s + _live_s:,.0f}",
            })

        if _perf:
            st.dataframe(pd.DataFrame(_perf), hide_index=True, width='stretch')

            # Delete by strategy
            with st.expander("\U0001f5d1\ufe0f Delete records by strategy"):
                _del_strat = st.selectbox("Select strategy to delete all its records",
                    ["-- select --"] + ["Institutional", "OptionSeller", "OptionBuyer", "Hedging"],
                    key="_del_strat_sel")
                _del_date_s = st.text_input("Limit to date (YYYY-MM-DD, leave blank = all dates)",
                    key="_del_strat_date", placeholder="e.g. 2026-07-14")
                if st.button("Delete selected strategy records", key="_del_strat_btn",
                             type="primary"):
                    if _del_strat != "-- select --":
                        _before = len(_at_all)
                        _at_all[:] = [t for t in _at_all
                            if not (t.get("strategy_type") == _del_strat
                                    and (_del_date_s == "" or t.get("date") == _del_date_s))]
                        _AUTO_LOG.write_text(
                            _json.dumps(_at_all, indent=2, default=str), encoding="utf-8")
                        st.success(f"Deleted {_before - len(_at_all)} record(s) for {_del_strat}.")
                        st.rerun()
                    else:
                        st.warning("Select a strategy first.")
        else:
            st.info("No performance data yet. Run the engine first.")

        st.divider()

        # Delete individual trade by ID
        st.subheader("Delete Individual Trade")
        _all_ids = [t.get("id", "") for t in _at_all if t.get("id")]
        if _all_ids:
            _col_del1, _col_del2 = st.columns([3, 1])
            _del_id = _col_del1.selectbox("Select Trade ID to delete", _all_ids, key="_at_del_id")
            if _col_del2.button("\U0001f5d1\ufe0f Delete", key="_at_del_btn", type="primary"):
                _before_d = len(_at_all)
                _at_all[:] = [t for t in _at_all if t.get("id") != _del_id]
                _AUTO_LOG.write_text(
                    _json.dumps(_at_all, indent=2, default=str), encoding="utf-8")
                st.success(f"Deleted trade: {_del_id}")
                st.rerun()
        else:
            st.info("No trades to delete.")


# ============================================================
#  TAB 10 — Mutual Fund Tracker
# ============================================================

with tab10:
    st.header("📊 Mutual Fund Tracker")
    st.caption(
        "Track NAV performance, simulate SIP, and compare funds vs NIFTY 50. "
        "Data from api.mfapi.in (free, no auth). Educational study only — not financial advice."
    )
    st.info(
        "💡 **How mutual funds differ from Nifty trading:**  "
        "NAV settles once daily (3 PM cut-off). No leverage, no intraday, no short-selling. "
        "Much safer than futures/options but no Stop-Loss automation possible."
    )

    # ── Fund selector ────────────────────────────────────────
    st.divider()

    # Category filter
    _cat_filter = st.radio(
        "Fund Category",
        ["All Funds", "🏷️ ELSS (Tax Saving)", "📈 Index Funds", "💼 Equity Funds"],
        horizontal=True,
        key="mf_cat_filter",
        help="Filter by category. ELSS = tax-saving under Section 80C with 3-year lock-in.")
    _fund_pool = (
        ELSS_FUNDS   if "ELSS"  in _cat_filter else
        INDEX_FUNDS  if "Index" in _cat_filter else
        EQUITY_FUNDS if "Equity" in _cat_filter else
        POPULAR_FUNDS
    )

    # ELSS education banner
    if "ELSS" in _cat_filter:
        st.info(
            "🏷️ **ELSS (Equity Linked Savings Scheme) — Section 80C Tax Benefit**\n\n"
            "- **Tax deduction**: Invest up to **₹1.5 lakh/year** → save up to **₹46,800 tax** (30% bracket)\n"
            "- **Lock-in**: 3 years (shortest among all 80C options)\n"
            "- **Returns**: Market-linked equity returns (historically 12-18% CAGR over 5+ years)\n"
            "- **vs FD / NSC / PPF**: Higher risk but much better long-term returns\n"
            "- **SIP works**: Invest ₹12,500/month → ₹1.5L/year tax benefit + compounding"
        )

    mf_col1, mf_col2 = st.columns([2, 1])

    with mf_col1:
        # Curated funds dropdown (filtered by category)
        _pop_opts = {f"{v['name']} [{v['category']}]": k for k, v in _fund_pool.items()}
        _pop_choice = st.selectbox(
            f"Choose from {_cat_filter.split(' ', 1)[-1] if ' ' in _cat_filter else 'popular'} funds",
            options=["-- select --"] + list(_pop_opts.keys()),
            key="mf_pop_sel")
        # OR search by name
        _mf_search = st.text_input(
            "Or search by fund name",
            placeholder="e.g. hdfc elss tax saver direct growth",
            key="mf_search_q")

    with mf_col2:
        _mf_years  = st.selectbox("History (years)", [1, 3, 5, 10], index=1, key="mf_years")
        _sip_amt   = st.number_input("Monthly SIP / ELSS amount (₹)", 500, 100000, 5000, 500,
                                      key="mf_sip",
                                      help="For ELSS: invest ₹12,500/month to claim full ₹1.5L 80C benefit")

    # Resolve scheme code
    _scheme_code = None
    _scheme_name = ""

    if _mf_search and len(_mf_search) >= 3:
        _results = search_funds(_mf_search, max_results=8)
        if _results:
            _names = [f"{r['schemeCode']} — {r['schemeName'][:60]}" for r in _results]
            _sel   = st.selectbox("Search results:", _names, key="mf_search_res")
            if _sel:
                _scheme_code = _sel.split(" — ")[0].strip()
                _scheme_name = _sel
        else:
            st.warning("No funds found. Try a different search term.")
    elif _pop_choice != "-- select --":
        _scheme_code = _pop_opts[_pop_choice]
        _scheme_name = _pop_choice

    if not _scheme_code:
        st.info("Select or search for a fund above to begin analysis.")

    # ── Load and display fund data ────────────────────────────
    if _scheme_code:
        with st.spinner(f"Loading NAV data for scheme {_scheme_code}..."):
            try:
                nav_df, meta = load_nav_history(_scheme_code, years=_mf_years)
            except Exception as _mf_err:
                st.error(f"Failed to load fund data: {_mf_err}")
                nav_df, meta = pd.DataFrame(), {}

        if not nav_df.empty:
            _fund_name  = meta.get("scheme_name", _scheme_name)
            _category   = meta.get("scheme_category", "")
            _amc        = meta.get("fund_house", "")
            _metrics    = compute_fund_metrics(nav_df)
            _sip_result = simulate_sip(nav_df, monthly_amount=_sip_amt)
            _compare_df = compare_with_nifty(nav_df)

            st.subheader(_fund_name)
            # Show ELSS lock-in badge if applicable
            _fund_info = POPULAR_FUNDS.get(_scheme_code, {})
            _is_elss   = _fund_info.get("tax_80c", False)
            if _is_elss:
                st.success(
                    "🏷️ **ELSS Fund — Section 80C eligible** | "
                    "3-year lock-in | Tax deduction up to ₹1,50,000/year | "
                    "Save up to ₹46,800 tax (at 30% bracket)"
                )
            st.caption(f"{_category}  |  {_amc}  |  Scheme code: {_scheme_code}")

            # ── KPI Row ───────────────────────────────────────
            _c1, _c2, _c3, _c4, _c5, _c6 = st.columns(6)
            _c1.metric("Current NAV",   f"₹{_metrics.get('current_nav', 0):,.2f}",
                       help="Latest published NAV (T+1 from previous trading day)")
            _c2.metric(f"CAGR ({_mf_years}yr)", f"{_metrics.get('cagr_pct', 0):+.2f}%",
                       help="Compound Annual Growth Rate over selected period")
            _c3.metric("Total Return",  f"{_metrics.get('total_return_pct', 0):+.1f}%",
                       help="Absolute return over selected period")
            _c4.metric("Sharpe Ratio",  f"{_metrics.get('sharpe_ratio', 0):.2f}",
                       help=">1 = good. Excess return per unit of volatility.")
            _c5.metric("Max Drawdown",  f"{_metrics.get('max_drawdown_pct', 0):.1f}%",
                       help="Worst peak-to-trough NAV fall")
            _c6.metric("Volatility",    f"{_metrics.get('volatility_pct', 0):.1f}%",
                       help="Annualised daily return standard deviation")

            st.divider()

            # ── NAV chart + Benchmark comparison ─────────────
            _tab_chart, _tab_sip, _tab_metrics, _tab_rolling = st.tabs([
                "📈 NAV Chart", "💰 SIP Simulator", "📋 Risk Metrics", "📅 Rolling Returns"
            ])

            with _tab_chart:
                fig_nav = go.Figure()

                if not _compare_df.empty:
                    # Fund vs NIFTY (indexed to 100)
                    fig_nav.add_trace(go.Scatter(
                        x=_compare_df["date"], y=_compare_df["fund_indexed"],
                        name=_fund_name[:35], line=dict(color="royalblue", width=2)))
                    fig_nav.add_trace(go.Scatter(
                        x=_compare_df["date"], y=_compare_df["nifty_indexed"],
                        name="NIFTY 50", line=dict(color="orange", width=2, dash="dash")))
                    fig_nav.update_yaxes(title_text="Indexed Value (Start = 100)")
                    st.caption(
                        "Both fund and NIFTY 50 indexed to 100 at start of period. "
                        "Value > 100 = positive return from that date."
                    )
                else:
                    # Just fund NAV
                    fig_nav.add_trace(go.Scatter(
                        x=nav_df["date"], y=nav_df["nav"],
                        name="NAV (₹)", line=dict(color="royalblue", width=2), fill="tozeroy"))
                    fig_nav.update_yaxes(title_text="NAV (₹)")

                # Drawdown shading
                _pv = nav_df["nav"].values
                _peak = np.maximum.accumulate(_pv)
                _dd   = (_pv - _peak) / _peak * 100
                fig_nav.add_trace(go.Scatter(
                    x=nav_df["date"], y=_dd,
                    name="Drawdown (%)", line=dict(color="red", width=1),
                    yaxis="y2", fill="tozeroy", fillcolor="rgba(255,0,0,0.1)",
                    visible="legendonly"))

                fig_nav.update_layout(
                    height=420,
                    yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Drawdown %"),
                    legend=dict(orientation="h"),
                    margin=dict(l=10, r=10, t=30, b=10),
                    hovermode="x unified")
                st.plotly_chart(fig_nav, width='stretch')

                # Fund vs NIFTY metrics table
                if not _compare_df.empty:
                    _nifty_ret = ((_compare_df["nifty_indexed"].iloc[-1] / 100) - 1) * 100
                    _fund_ret  = ((_compare_df["fund_indexed"].iloc[-1] / 100)  - 1) * 100
                    _out_perf  = _fund_ret - _nifty_ret
                    _cmp = pd.DataFrame([
                        {"Metric": "Period Return (%)",    "Fund": f"{_fund_ret:+.2f}",  "NIFTY 50": f"{_nifty_ret:+.2f}"},
                        {"Metric": "Alpha vs NIFTY (%)",   "Fund": f"{_out_perf:+.2f}", "NIFTY 50": "—"},
                        {"Metric": "CAGR (%)",             "Fund": f"{_metrics.get('cagr_pct',0):+.2f}", "NIFTY 50": "~14"},
                        {"Metric": "Volatility (%)",       "Fund": f"{_metrics.get('volatility_pct',0):.1f}", "NIFTY 50": "~16"},
                        {"Metric": "Max Drawdown (%)",     "Fund": f"{_metrics.get('max_drawdown_pct',0):.1f}", "NIFTY 50": "~-30"},
                    ])
                    st.dataframe(_cmp, hide_index=True, width='stretch')
                    _alpha_color = "🟢" if _out_perf > 0 else "🔴"
                    st.caption(f"{_alpha_color} Fund {'outperformed' if _out_perf > 0 else 'underperformed'} NIFTY 50 by **{_out_perf:+.2f}%** over this period.")

            with _tab_sip:
                if _sip_result:
                    _sr  = _sip_result
                    _s1, _s2, _s3, _s4 = st.columns(4)
                    _s1.metric("Total Invested",    f"₹{_sr['total_invested']:,.0f}",
                               help="SIP of ₹{:,.0f}/month × {} months".format(_sip_amt, _sr['months']))
                    _s2.metric("Current Value",     f"₹{_sr['current_value']:,.0f}",
                               delta=f"₹{_sr['current_value'] - _sr['total_invested']:+,.0f}")
                    _s3.metric("Absolute Return",   f"{_sr['absolute_return_pct']:+.2f}%")
                    _s4.metric("XIRR (approx)",     f"{_sr['xirr_approx_pct']:+.2f}%",
                               help="Annualised return considering monthly cash flows (XIRR approximation)")

                    _ser = _sr["series"]
                    fig_sip = go.Figure()
                    fig_sip.add_trace(go.Scatter(
                        x=_ser["date"], y=_ser["value_cum"],
                        name="Portfolio Value", fill="tozeroy",
                        line=dict(color="green", width=2)))
                    fig_sip.add_trace(go.Scatter(
                        x=_ser["date"], y=_ser["invested_cum"],
                        name="Amount Invested", line=dict(color="gray", dash="dash", width=1.5)))
                    fig_sip.update_layout(
                        xaxis_title="Date", yaxis_title="Value (₹)",
                        height=350, margin=dict(l=10, r=10, t=30, b=10),
                        hovermode="x unified")
                    st.plotly_chart(fig_sip, width='stretch')
                    st.caption(
                        f"💡 **SIP insight:** ₹{_sip_amt:,}/month for {_sr['months']} months "
                        f"→ Invested ₹{_sr['total_invested']:,.0f}, Current value ₹{_sr['current_value']:,.0f}. "
                        f"Units accumulated: {_sr['units_accumulated']:,.2f} @ NAV ₹{_sr['current_nav']:,.4f}"
                    )
                else:
                    st.info("Not enough data to simulate SIP for this period.")

                st.divider()
                st.markdown("""
**SIP vs Lump Sum — key difference for mutual funds:**
- **SIP** = invest fixed amount every month (rupee cost averaging) — **safer**, reduces timing risk
- **Lump Sum** = invest entire amount at once — higher reward if timed perfectly, higher risk if market falls immediately
- **For most retail investors**: SIP is recommended (no need to time the market)
- **Key advantage over Nifty trading**: SIP has NO stop-loss worries, NO expiry, NO margin calls
                """)

                # ELSS Tax Calculator (only for ELSS funds)
                if _is_elss:
                    st.divider()
                    st.subheader("🏷️ ELSS Tax Saving Calculator")
                    _tc1, _tc2, _tc3 = st.columns(3)
                    _annual_invest = _tc1.number_input(
                        "Annual ELSS investment (₹)", 500, 150000, 150000, 5000,
                        key="elss_annual",
                        help="Max ₹1,50,000 is eligible for 80C deduction"
                    )
                    _tax_bracket = _tc2.selectbox(
                        "Your tax bracket",
                        ["5%", "20%", "30%"],
                        index=2, key="elss_bracket",
                        help="Select your income tax slab rate"
                    )
                    _bracket_rate = int(_tax_bracket.replace("%","")) / 100

                    _eligible    = min(_annual_invest, 150000)
                    _tax_saved   = round(_eligible * _bracket_rate * 1.04)  # +4% cess
                    _net_invest  = _annual_invest - _tax_saved
                    _future_val  = round(_annual_invest * (((1 + _metrics.get("cagr_pct", 12)/100) ** 3 - 1) / (_metrics.get("cagr_pct", 12)/100)))

                    _tc3.metric("Tax Saved (per year)", f"₹{_tax_saved:,.0f}",
                                help="Income tax + 4% cess saved under Section 80C")
                    st.markdown(f"""
| Item | Amount |
|---|---|
| Annual ELSS investment | ₹{_annual_invest:,.0f} |
| Section 80C deduction eligible | ₹{_eligible:,.0f} |
| Tax saved ({_tax_bracket} + 4% cess) | **₹{_tax_saved:,.0f}** |
| Effective net investment after tax saving | ₹{_annual_invest - _tax_saved:,.0f} |
| Estimated 3-yr maturity value* | ₹{_future_val:,.0f} |
| Monthly SIP for ₹1.5L/yr benefit | ₹{150000 // 12:,.0f}/month |

_*At {_metrics.get('cagr_pct', 12):.1f}% CAGR (this fund's recent return). Actual returns will vary._
                    """)

            with _tab_metrics:
                _m = _metrics
                _met_data = {
                    "Metric": [
                        "CAGR", "Total Return", "Annualised Volatility",
                        "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
                        "Max Drawdown", "Best Day", "Worst Day",
                        "% Profitable Days", "Data Period (years)", "Data Points",
                    ],
                    "Value": [
                        f"{_m.get('cagr_pct', 0):+.2f}%",
                        f"{_m.get('total_return_pct', 0):+.1f}%",
                        f"{_m.get('volatility_pct', 0):.2f}%",
                        f"{_m.get('sharpe_ratio', 0):.2f}",
                        f"{_m.get('sortino_ratio', 0):.2f}",
                        f"{_m.get('calmar_ratio', 0):.2f}",
                        f"{_m.get('max_drawdown_pct', 0):.2f}%",
                        f"+{_m.get('best_day_pct', 0):.2f}%",
                        f"{_m.get('worst_day_pct', 0):.2f}%",
                        f"{_m.get('profitable_days_pct', 0):.1f}%",
                        f"{_m.get('n_years', 0):.1f}",
                        str(_m.get("n_days", 0)),
                    ],
                    "Interpretation": [
                        ">12% = good for equity MF",
                        f"Over {_m.get('n_years',0):.1f} years",
                        "<18% = low-moderate risk",
                        ">1 = good, >2 = excellent",
                        "Like Sharpe but only penalises down days",
                        ">0.5 = acceptable, >1 = good",
                        "Worst peak-to-trough NAV fall",
                        "Best single-day gain",
                        "Worst single-day loss",
                        "Days with positive NAV change",
                        "Historical data available",
                        "Total NAV records",
                    ],
                }
                st.dataframe(pd.DataFrame(_met_data), hide_index=True, width='stretch')

                with st.expander("🔍 Mutual Fund vs Nifty Trading — Safety Comparison"):
                    st.markdown(f"""
| Risk Factor | This Fund | Nifty Futures | Nifty Options (Buyer) |
|---|---|---|---|
| **Max loss possible** | 100% of invested (rare) | Unlimited (without SL) | 100% of premium |
| **Daily loss potential** | ≈ {_m.get('worst_day_pct', -3):.1f}% | −5-10% of margin | −100% of premium |
| **Leverage** | None | 5-10× | 50-100× |
| **Stop Loss** | Manual (next day NAV) | Instant SL possible | Instant SL possible |
| **Expiry** | No expiry | Monthly expiry | Weekly expiry |
| **Margin call** | Never | Yes, daily MTM | No (premium paid upfront) |
| **Time decay** | No | No | Yes (Theta −₹ daily) |
| **Minimum capital** | ₹500 SIP | ₹1.5–6 lakh | ₹1,000–50,000 |
| **Recommended for** | Long-term investors | Experienced traders | Very experienced traders |

**Verdict**: Mutual funds are **significantly safer** for wealth creation. Trading is for those with time, skill, and risk appetite.
                    """)

            with _tab_rolling:
                _roll_df = compute_rolling_returns(nav_df)
                if not _roll_df.empty:
                    fig_roll = go.Figure()
                    for col, colour, label in [
                        ("rolling_1y", "blue",   "1-Year Rolling CAGR"),
                        ("rolling_3y", "green",  "3-Year Rolling CAGR"),
                        ("rolling_5y", "orange", "5-Year Rolling CAGR"),
                    ]:
                        _rdata = _roll_df[_roll_df[col].notna()]
                        if not _rdata.empty:
                            fig_roll.add_trace(go.Scatter(
                                x=_rdata["date"], y=_rdata[col],
                                name=label, line=dict(color=colour, width=2)))

                    fig_roll.add_hline(y=0,  line_color="gray", line_dash="dot")
                    fig_roll.add_hline(y=12, line_color="green", line_dash="dash",
                                       annotation_text="12% benchmark")
                    fig_roll.update_layout(
                        xaxis_title="Date",
                        yaxis_title="Annualised Return (%)",
                        height=380,
                        margin=dict(l=10, r=10, t=30, b=10),
                        hovermode="x unified")
                    st.plotly_chart(fig_roll, width='stretch')
                    st.caption(
                        "Rolling returns show how CAGR varied over time. "
                        "Consistent positive 3-yr rolling returns = quality fund. "
                        "Wide swings = high volatility."
                    )
                else:
                    st.info("Not enough history for rolling return analysis.")

    # ── Multi-fund comparison ─────────────────────────────────
    st.divider()
    st.subheader("⚡ Quick Compare — All Funds (1-Year)")
    st.caption("Compares Index, Equity, and ELSS funds side by side. Takes ~20 seconds.")

    _cmp_cat = st.radio(
        "Compare category",
        ["All", "ELSS only", "Index only", "Equity only"],
        horizontal=True,
        key="mf_cmp_cat")
    _cmp_pool = (
        ELSS_FUNDS   if _cmp_cat == "ELSS only"   else
        INDEX_FUNDS  if _cmp_cat == "Index only"  else
        EQUITY_FUNDS if _cmp_cat == "Equity only" else
        POPULAR_FUNDS
    )

    if st.button("📊 Run Comparison", key="mf_compare_btn",
                 help="Fetches 1-year NAV for selected category and ranks them"):
        _comp_rows = []
        _prog = st.progress(0)
        _pool_items = list(_cmp_pool.items())
        for idx, (code, info) in enumerate(_pool_items):
            _prog.progress((idx + 1) / len(_pool_items))
            try:
                _ndf, _nmeta = load_nav_history(code, years=1)
                _nm = compute_fund_metrics(_ndf)
                _sip_r = simulate_sip(_ndf, monthly_amount=5000)
                _comp_rows.append({
                    "Fund":          info["name"][:45],
                    "Category":      info["category"],
                    "80C Eligible":  "✅" if info.get("tax_80c") else "—",
                    "CAGR (1yr) %":  f"{_nm.get('cagr_pct',0):+.2f}",
                    "Sharpe":        f"{_nm.get('sharpe_ratio',0):.2f}",
                    "Max DD %":      f"{_nm.get('max_drawdown_pct',0):.1f}",
                    "Volatility %":  f"{_nm.get('volatility_pct',0):.1f}",
                    "SIP ₹5k/mo":    f"₹{_sip_r.get('current_value', 0):,.0f}",
                    "SIP XIRR %":    f"{_sip_r.get('xirr_approx_pct', 0):+.1f}",
                    "Risk":          info["risk"],
                    "Code":          code,
                })
            except Exception:
                pass
        _prog.empty()

        if _comp_rows:
            _cdf = pd.DataFrame(_comp_rows)
            st.dataframe(
                _cdf.sort_values("CAGR (1yr) %", ascending=False).drop(columns=["Code"]),
                hide_index=True, column_config={
                    "Fund":         st.column_config.TextColumn(width=280),
                    "Category":     st.column_config.TextColumn(width=140),
                    "CAGR (1yr) %": st.column_config.TextColumn(width=95,
                                        help="1-year CAGR. Higher = better short-term performance."),
                    "Sharpe":       st.column_config.TextColumn(width=70,
                                        help=">1 = good risk-adjusted return"),
                    "Max DD %":     st.column_config.TextColumn(width=80,
                                        help="Worst drawdown in 1 year. Less negative = safer."),
                    "SIP ₹5k/mo":   st.column_config.TextColumn(width=110,
                                        help="Value today if you had invested ₹5,000/month for 1 year"),
                    "SIP XIRR %":   st.column_config.TextColumn(width=95,
                                        help="Annualised SIP return (XIRR approx)"),
                    "Risk":         st.column_config.TextColumn(width=100),
                })
            st.caption("⚠️ 1-year returns are noisy. Always evaluate 3-5 year track record before investing.")


# ============================================================
#  TAB 11 — Market Microstructure (Who Wins / Who Loses)
# ============================================================

with tab11:
    st.header(f"🎰 Market Microstructure — {symbol}")
    st.caption("Identify crowd vs smart money. Know WHO WINS in crowded trades.")
    st.divider()
   
    # Load option chain data
    try:
        oc_file = f"data/option_chain_{symbol}.csv"
        if not os.path.exists(oc_file):
            st.warning(f"Option chain file not found: {oc_file}")
            st.info("Run the NSE data cron job first to get live option chain data.")
        else:
            oc_df = pd.read_csv(oc_file)
           
            # ---- Section 1: Options Flow Analysis ----
            st.subheader("📊 1. Options Flow Analysis")
            st.caption("Call vs Put buying pressure. High call ratio = crowd is bullish = watch out!")
           
            flow = analyze_options_flow(oc_df)
           
            _flow_col1, _flow_col2, _flow_col3, _flow_col4 = st.columns(4)
            with _flow_col1:
                st.metric("Call Volume Ratio", f"{flow.get('call_volume_ratio', 0):.1f}%",
                          help="% of total volume that is calls. >60% = crowd buying calls")
            with _flow_col2:
                st.metric("Put Volume Ratio", f"{flow.get('put_volume_ratio', 0):.1f}%",
                          help="% of total volume that is puts.")
            with _flow_col3:
                st.metric("Call IV (Avg)", f"{flow.get('call_avg_iv', 50):.1f}",
                          help="Average implied volatility of call options.")
            with _flow_col4:
                st.metric("Put IV (Avg)", f"{flow.get('put_avg_iv', 50):.1f}",
                          help="Average IV of put options.")
           
            st.markdown(f"""
### Sentiment: {flow.get('sentiment', '⚪ NEUTRAL')}
**Crowd Conviction**: {flow.get('crowd_conviction', 'MODERATE')}

{['⚠️ **CRITICAL**: Crowd is EXTREMELY BULLISH at {flow.get("call_volume_ratio", 50)}% call ratio. Premium is likely OVERHEATED. Smart money may be fading this move.',
  '⚠️ Crowd is strongly bullish. Most retail traders have bought CE. This is a contrarian warning signal.',
  '✓ Market sentiment is balanced. Lower crowd concentration = potential edge for disciplined traders.',
  '✓ Crowd is scattered. Fewer herding risk.'][
    0 if flow.get('call_volume_ratio', 50) > 65 else
    1 if flow.get('call_volume_ratio', 50) > 60 else
    2 if flow.get('call_volume_ratio', 50) > 55 else
    3]}
            """)
           
            st.divider()
           
            # ---- Section 2: OI Heatmap ----
            st.subheader("🔥 2. Open Interest Heatmap")
            st.caption("Which strikes are being accumulated? Which are abandoned? Accumulation = smart money buying.")
           
            heatmap = get_oi_heatmap(oc_df)
            if not heatmap.empty:
                # Separate CE and PE
                ce_hm = heatmap[heatmap['opt_type'] == 'CE'].sort_values('buying_pressure', ascending=False).head(10)
                pe_hm = heatmap[heatmap['opt_type'] == 'PE'].sort_values('buying_pressure', ascending=False).head(10)
               
                _hm_col1, _hm_col2 = st.columns(2)
               
                with _hm_col1:
                    st.markdown("#### CE Top Accumulation Zones")
                    if not ce_hm.empty:
                        st.dataframe(
                            ce_hm[['strike', 'volume', 'oi', 'iv', 'buying_pressure']].rename(columns={
                                'strike': 'Strike', 'volume': 'Volume', 'oi': 'OI',
                                'iv': 'IV', 'buying_pressure': 'Pressure Score'
                            }),
                            hide_index=True)
               
                with _hm_col2:
                    st.markdown("#### PE Top Accumulation Zones")
                    if not pe_hm.empty:
                        st.dataframe(
                            pe_hm[['strike', 'volume', 'oi', 'iv', 'buying_pressure']].rename(columns={
                                'strike': 'Strike', 'volume': 'Volume', 'oi': 'OI',
                                'iv': 'IV', 'buying_pressure': 'Pressure Score'
                            }),
                            hide_index=True)
           
            st.divider()
           
            # ---- Section 3: Crowd Bias Detector ----
            st.subheader("👥 3. Crowd Bias Detector")
            st.caption("Strikes where CROWD is gathered = EXPENSIVE = LOSSES. Where is the dumb money?")
           
            crowd_strikes = detect_crowd_bias(oc_df)
            if crowd_strikes:
                _cb_data = []
                for cs in crowd_strikes[:5]:
                    _cb_data.append({
                        'Strike': cs['strike'],
                        'Option': cs['opt_type'],
                        'Crowd %': f"{cs['crowd_pct']:.1f}%",
                        'Crowd Level': cs['crowd_level'],
                        'Volume': cs['volume'],
                        'IV': cs['iv'],
                        'Risk': cs['risk_level']
                    })
               
                _cb_df = pd.DataFrame(_cb_data)
                st.dataframe(_cb_df, hide_index=True)
               
                if crowd_strikes and crowd_strikes[0]['crowd_pct'] > 10:
                    st.warning(f"""
🚨 **HIGH CROWD CONCENTRATION DETECTED**

**Strike {crowd_strikes[0]['strike']} {crowd_strikes[0]['opt_type']}** has {crowd_strikes[0]['crowd_pct']:.1f}% of all volume.

**What this means:**
- **Crowd is heavily positioned here** → IV is likely OVERHEATED
- **Most buyers paid HIGH premium** → They are at risk of losses
- **Smart money likely SOLD** to this crowd → Collecting premium
- **Probability**: Strike jumpers and theta decay will hurt crowd
- **Smart trade**: FADE this strike, find lower IV zones (Tab 3 item below)

**Action**: Look for isolated sellers (low crowd %) with similar technical setup.
                    """)
           
            st.divider()
           
            # ---- Section 4: IV Rank ----
            st.subheader("📈 4. IV Rank (Expensive or Cheap?)")
            st.caption("If IV Rank = 75%, options are EXPENSIVE (premium paid high). If = 25%, they're CHEAP (good entry).")
           
            iv_rank = calculate_iv_rank(oc_df, symbol=symbol)
           
            _iv_col1, _iv_col2, _iv_col3 = st.columns(3)
            with _iv_col1:
                st.metric("IV Rank Percentile", f"{iv_rank:.0f}%")
            with _iv_col2:
                st.metric("Status", "🔴 EXPENSIVE" if iv_rank > 70 else "🟡 FAIR" if iv_rank > 40 else "🟢 CHEAP",
                          help="Expensive = sellers have edge, Cheap = buyers have edge")
            with _iv_col3:
                st.metric("Recommendation",
                          "SELL (earn premium)" if iv_rank > 70 else "NEUTRAL" if iv_rank > 40 else "BUY (good value)",
                          help="General guidance only")
           
            st.markdown(f"""
### Interpretation
- **IV Rank > 70**: Options are EXPENSIVE (cost high). Good for SELLERS, bad for BUYERS. Crowd likely overpaying.
- **IV Rank 40-70**: Fair value. Normal trading range.
- **IV Rank < 40**: Options are CHEAP (cost low). Good for BUYERS, bad for SELLERS. Smart entry zone for aggressive trades.

**For this {symbol}**: IV Rank = {iv_rank:.0f}% → {"AVOID buying high premium, consider selling" if iv_rank > 70 else "Neutral zone" if iv_rank > 40 else "Good buying opportunity for disciplined traders"}
            """)
           
            st.divider()
           
            # ---- Section 5: Smart Entry Zones ----
            st.subheader("💡 5. Smart Entry Zones")
            st.caption("Where SMART MONEY enters: Low IV, Low Crowd, High Volume (isolation).")
           
            smart_zones = find_smart_entry_zones(oc_df, iv_rank)
            if not smart_zones.empty:
                st.dataframe(
                    smart_zones.head(8)[['strike', 'opt_type', 'iv', 'ltp', 'volume', 'entry_quality']].rename(columns={
                        'strike': 'Strike', 'opt_type': 'Type', 'iv': 'IV', 'ltp': 'LTP',
                        'volume': 'Volume', 'entry_quality': 'Quality'
                    }),
                    hide_index=True)
                st.caption("⭐ Quality = ⭐⭐⭐ is BEST value entry (lowest IV + lowest crowd).")
            else:
                st.info("No low-IV entry zones found. IV is generally low across all strikes.")
           
            st.divider()
           
            # ---- Section 6: Realistic P&L Simulator ----
            st.subheader("💰 6. Realistic P&L Simulator")
            st.caption("What does a +50% trade ACTUALLY net after slippage, brokerage, and taxes?")
           
            _pnl_col1, _pnl_col2, _pnl_col3, _pnl_col4 = st.columns(4)
            with _pnl_col1:
                _pnl_entry = st.number_input("Entry Price (₹)", min_value=10, max_value=5000, value=100, key="pnl_entry")
            with _pnl_col2:
                _pnl_exit = st.number_input("Exit Price (₹)", min_value=10, max_value=5000, value=150, key="pnl_exit")
            with _pnl_col3:
                _pnl_qty = st.number_input("Quantity (lots)", min_value=1, max_value=50, value=1, key="pnl_qty")
            with _pnl_col4:
                _pnl_brok = st.slider("Brokerage %", 0.01, 0.10, 0.03, key="pnl_brok")
           
            _pnl_result = calculate_realistic_pnl(
                _pnl_entry, _pnl_exit, _pnl_qty,
                brokerage_pct=_pnl_brok, slippage_pct=0.5, tax_rate=20
            )
           
            if _pnl_result:
                _pnl_c1, _pnl_c2, _pnl_c3, _pnl_c4 = st.columns(4)
                with _pnl_c1:
                    st.metric("Gross P&L", f"₹{_pnl_result['gross_pnl']:,.0f}",
                              f"{_pnl_result.get('gross_pnl_pct', 0):+.1f}%")
                with _pnl_c2:
                    st.metric("Total Costs", f"₹{_pnl_result['total_costs']:,.0f}",
                              f"{_pnl_result.get('cost_as_pct_of_gross', 0):.0f}% of gross")
                with _pnl_c3:
                    st.metric("Tax Cost", f"₹{_pnl_result['tax_cost']:,.0f}")
                with _pnl_c4:
                    st.metric("Net P&L", f"₹{_pnl_result['net_pnl']:,.0f}",
                              f"{_pnl_result.get('net_pnl_pct', 0):+.1f}%")
               
                st.markdown(f"""
### {_pnl_result['result_quality']}

| Component | Amount | % of Turnover |
|-----------|--------|---|
| Entry Price | ₹{_pnl_result['entry_price']:,.2f} | — |
| Exit Price | ₹{_pnl_result['exit_price']:,.2f} | — |
| Quantity | {_pnl_result['quantity']} lots | — |
| **Gross P&L** | **₹{_pnl_result['gross_pnl']:,.0f}** | **{_pnl_result.get("gross_pnl_pct", 0):+.1f}%** |
| Slippage (entry + exit) | −₹{_pnl_result['slippage_cost']:,.0f} | {(_pnl_result['slippage_cost'] / (_pnl_result['entry_price'] + _pnl_result['exit_price']) / _pnl_result['quantity'] * 100):.2f}% |
| Brokerage ({_pnl_brok:.2f}%) | −₹{_pnl_result['brokerage_cost']:,.0f} | {(_pnl_result['brokerage_cost'] / (_pnl_result['entry_price'] + _pnl_result['exit_price']) / _pnl_result['quantity'] * 100):.2f}% |
| STCG Tax (20%) | −₹{_pnl_result['tax_cost']:,.0f} | {(_pnl_result['tax_cost'] / _pnl_result['gross_pnl'] * 100) if _pnl_result['gross_pnl'] > 0 else 0:.1f}% of profit |
| **NET P&L** | **₹{_pnl_result['net_pnl']:,.0f}** | **{_pnl_result.get("net_pnl_pct", 0):+.1f}%** |

**Hidden Cost Impact**: {_pnl_result.get('cost_as_pct_of_gross', 0):.0f}% of your gross profit disappears to costs!
                """)
               
                if _pnl_result['net_pnl'] < _pnl_result['gross_pnl'] * 0.5:
                    st.warning("""
⚠️ **Most of your profits are eaten by costs!**

To survive:
1. **Reduce slippage**: Use limit orders, trade liquid strikes only
2. **Negotiate brokerage**: Should be < 0.02% for active traders
3. **Minimize holding time**: Theta decay + tax eating gains
4. **Size bigger moves**: Need >75% gross profit to get >25% net
                    """)
           
            st.divider()
           
            # ---- Section 7: Crowd vs Smart Analysis ----
            st.subheader("🎯 Crowd vs Smart Money Prediction")
            st.caption("Where is dumb money? Where are smart traders positioned?")
           
            if crowd_strikes:
                analysis = crowd_vs_smart_analysis(oc_df, crowd_strikes)
                st.markdown(f"""
### Analysis Summary

| Factor | Crowd Gathered | Smart Money |
|--------|---|---|
| **Strike** | {analysis.get('crowd_gathered_at', 'N/A')} | {analysis.get('smart_entry_at', 'N/A')} |
| **IV** | {analysis.get('crowd_iv', 'N/A')} (Expensive) | {analysis.get('smart_iv', 'N/A')} (Cheap) |
| **Crowd %** | {analysis.get('crowd_crowd_pct', 'N/A')}% (HIGH) | Low (Smart selective) |
| **Expected Outcome** | Premium bleed, Theta decay loss | Value entry, Higher win rate |

### Probability Prediction
{analysis.get('probability_prediction', 'Neutral')}

**Action**:
- If you BOUGHT crowd strike → Consider exiting early (theta decay accelerates)
- If you AVOIDED crowd strike → Good discipline! Enter smart zones.
- If you SOLD crowd strike → Well positioned! Collect premium.
                """)
           
            with st.expander("📚 How to Read This Tab"):
                st.markdown("""
### Understanding Market Microstructure

**Why this matters:**
- When 10,000 retail traders see "AI says BULLISH → Buy CE", they all buy at the SAME time
- This CROWDS the same strike, INCREASES demand, RAISES IV and premium prices
- The LAST buyers pay the HIGHEST price (that's YOU if you're late)
- Early sellers (smart money) pocket the premium while dumb money gets theta-decayed

**Key concepts:**

**1. Options Flow**: Call/Put ratio shows crowd direction. >65% calls = everyone is bullish = contrarian warning.

**2. OI Heatmap**: Where do strikes have high volume? That's where crowd is gathered = expensive entry = risk of loss.

**3. Crowd Bias**: Strikes with >10% of all volume = dumb money concentrated here = sellers winning.

**4. IV Rank**: If IV Rank = 80%, options cost a LOT (sellers happy, buyers sad). If = 20%, cheap entry.

**5. Smart Entry Zones**: Low IV + Low crowd + high technical confluence = where experienced traders play.

**6. Realistic P&L**:
- A "+50%" trade might only net +15% after slippage (−0.5%), brokerage (−0.03%), taxes (−20%)
- Crowd often fails because they don't account for these hidden costs

**7. Crowd vs Smart**: Where are masses? Other direction. Where are experienced traders? Quiet zones with good value.

**Action Plan**:
1. Check Options Flow → Is crowd extremely bullish? If yes, consider fading
2. Check Crowd Bias → Which strikes have >10% volume? AVOID those
3. Check IV Rank → Is IV expensive? If yes, SELL premium. If cheap, BUY
4. Check Smart Entry Zones → Enter these strikes instead (lower IV = higher win rate)
5. Use Realistic P&L → Set expectations. Know your costs before trading
6. Repeat: Contrarian trades (opposite of crowd) have higher win probability
                """)
           
    except Exception as e:
        st.error(f"Error loading market microstructure analysis: {e}")
        st.info("Check that option chain data is available and properly formatted.")


# ============================================================
#  TAB 12 — Logic Optimization Agent (Intelligent Monitoring & Tuning)
# ============================================================

with tab12:
    st.header("🤖 Logic Optimization Agent")
    st.caption("Active Reinforcement & Parameter Tuning Agent Layer. Analyzes metrics, monitors market structure, and refines logic limits.")
    st.divider()

    try:
        from src.agent_logic import DecisionOptimizerAgent
        agent = DecisionOptimizerAgent(cfg)

        # 1. Load context data
        trades_list = tt.load_trades()
        performance_data = agent.analyze_journal_metrics(trades_list)
       
        # We need spots, futures, and vix context. Get them from loaded state
        vix_val = 0.0
        try:
            oc_files_list = sorted(
                _g.glob(str(Path(__file__).parent / "downloads" / "option_chain_*.json")),
                key=lambda p: Path(p).stat().st_mtime, reverse=True)
            if oc_files_list:
                _oc_json_data = _js2.loads(Path(oc_files_list[0]).read_bytes().decode("utf-8-sig"))
                vix_val = float(_oc_json_data.get("vix", 0) or 0)
        except Exception:
            pass
           
        regime_data = agent.evaluate_market_regime(futures_df, chain_df, vix_val)
        optimizations = agent.optimize_logic_parameters(performance_data, regime_data)

        # ---- Section 1: Agent Dashboard Overview ----
        _c1, _c2, _c3 = st.columns(3)
        with _c1:
            st.metric("Risk Allocation Rating", f"{optimizations['risk_allocation_multiplier']:.2f}x",
                      help="lot size sizing coefficient. Drops if consecutively losing; rises if highly winnable.")
        with _c2:
            st.metric("Suggested Stop ATR Mult.", f"{optimizations['optimal_sl_atr_multiplier']}x",
                      help="optimal stop-loss width parameter suggested based on current segment volatility.")
        with _c3:
            st.metric("Suggested Target ATR Mult.", f"{optimizations['optimal_target_atr_multiplier']}x")

        # ---- Section 2: Agent Logs and Insights ----
        st.subheader("💡 Optimization Recommendations & Explanations")
        for reason in optimizations["logic_explanations"]:
            st.info(f"✔️ {reason}")
        if not optimizations["logic_explanations"]:
            st.success("✔️ Default trade parameters (config.yaml) are currently optimal for this quiet regime.")

        st.markdown(f"**Recommended Focus Zone**: `{optimizations['recommended_regime_focus']}`")

        # ---- Section 3: Performance Audit ----
        st.divider()
        st.subheader("📊 Trade Performance Feedback Loop")
       
        _pcol1, _pcol2, _pcol3, _pcol4 = st.columns(4)
        with _pcol1:
            st.metric("Total Logged Trades", performance_data["total_trades"])
        with _pcol2:
            st.metric("Completed/Closed", performance_data.get("completed_trades", 0))
        with _pcol3:
            st.metric("Win Rate", f"{performance_data.get('win_rate', 0.0)}%" if performance_data.get("completed_trades", 0) > 0 else "—")
        with _pcol4:
            st.metric("Profit Factor", performance_data.get("profit_factor", "—") if performance_data.get("completed_trades", 0) > 0 else "—")

        if performance_data.get("consecutive_losses", 0) > 0:
            if performance_data["streak_alert"]:
                st.error(f"⚠️ **CONSECUTIVE LOSS STREAK**: [{performance_data['consecutive_losses']}] losses in a row detected. Slow down trading.")
            else:
                st.warning(f"ℹ️ Current max consecutive losing streak is {performance_data['consecutive_losses']} trades.")

        # Strategies breakdown table
        _stats = performance_data.get("strategy_stats", [])
        if _stats:
            st.markdown("#### Performance Breakdown by Strategy")
            st.dataframe(pd.DataFrame(_stats).rename(columns={
                "strategy": "Strategy Type",
                "total_pnl": "Net P&L (₹)",
                "win_rate": "Win Rate (%)",
                "count": "Total Trades"
            }), hide_index=True)

        # ---- Section 4: Market Context Audit ----
        st.divider()
        st.subheader("🌐 Current Market Health Summary")
       
        _mcol1, _mcol2, _mcol3 = st.columns(3)
        with _mcol1:
            st.metric("Trend State", regime_data.get("trend", "N/A"))
        with _mcol2:
            st.metric("VIX Regime rating", regime_data.get("vix_regime", "N/A"))
        with _mcol3:
            st.metric("ATR % of Price", f"{regime_data.get('atr_pct_of_price', 0.0)}%")

        st.caption("🤖 *Learning Loop*: Performance metrics are audited on every app load to dynamically shift execution tolerances.")

    except Exception as agent_err:
        st.error(f"Error launching Logic Optimization Agent: {agent_err}")
        st.info("Check agent logic and configurations.")


# ============================================================
#  TAB 13 — Live Algo Trade (Scaffold)
# ============================================================

with tab13:
    st.header("🚀 Live Algo Trade")
    st.caption(
        "Automated auto-trader: enters and exits option strategies on its own using the "
        "same proven paper-trade exit logic (fixed max-loss, profit-target, and time exit). "
        "Fields marked 🔴 are mandatory."
    )
    st.info(
        "🤖 **Main workflow:** configure the strategy and risk limits in Steps 1–3, then arm the "
        "**Automated Auto-Trader** at the bottom — it handles entry and exit automatically. "
        "The manual Step 4 controls are for one-off testing."
    )

    if "live_algo_kill_switch" not in st.session_state:
        st.session_state["live_algo_kill_switch"] = False
    if "live_algo_last_dryrun_ok" not in st.session_state:
        st.session_state["live_algo_last_dryrun_ok"] = False

    def _mask_secret(val: str) -> str:
        if not val:
            return "Not set"
        if len(val) <= 6:
            return "***"
        return f"{val[:3]}...{val[-2:]}"

    def _build_live_legs(strategy: str, strike_inputs: dict) -> list[dict]:
        if strategy == "Iron Condor (Defined Risk)":
            return [
                {"action": "BUY", "option_type": "PE", "strike": int(strike_inputs["buy_pe"])},
                {"action": "SELL", "option_type": "PE", "strike": int(strike_inputs["sell_pe"])},
                {"action": "SELL", "option_type": "CE", "strike": int(strike_inputs["sell_ce"])},
                {"action": "BUY", "option_type": "CE", "strike": int(strike_inputs["buy_ce"])},
            ]
        if strategy == "Bull Put Spread":
            return [
                {"action": "SELL", "option_type": "PE", "strike": int(strike_inputs["sell_pe"])},
                {"action": "BUY", "option_type": "PE", "strike": int(strike_inputs["buy_pe"])},
            ]
        if strategy == "Bear Call Spread":
            return [
                {"action": "SELL", "option_type": "CE", "strike": int(strike_inputs["sell_ce"])},
                {"action": "BUY", "option_type": "CE", "strike": int(strike_inputs["buy_ce"])},
            ]
        if strategy == "Short Strangle":
            return [
                {"action": "SELL", "option_type": "PE", "strike": int(strike_inputs["sell_pe"])},
                {"action": "SELL", "option_type": "CE", "strike": int(strike_inputs["sell_ce"])},
            ]
        if strategy == "Long Call":
            return [{"action": "BUY", "option_type": "CE", "strike": int(strike_inputs["buy_ce"]) }]
        return [{"action": "BUY", "option_type": "PE", "strike": int(strike_inputs["buy_pe"]) }]

    st.warning(
        "⚠️ Safety: real orders are sent only after you enable LIVE mode, pass the "
        "pre-flight checklist, and type the confirmation text. Dry-run is ON by default."
    )
    with st.expander("ℹ️ What do I have to fill in? (mandatory fields)", expanded=False):
        st.markdown(
            "You only need these — everything else has safe defaults:\n\n"
            "- 🔴 **Broker** and **Symbol** (just below)\n"
            "- 🔴 **Broker credentials** — Step 1\n"
            "- 🔴 **Strategy, Expiry, and Strikes** — Step 2\n"
            "- 🔴 **Stop-Loss and Target** — Step 3\n\n"
            "Then scroll to the **🤖 Automated Auto-Trader** at the bottom, set the max-loss / "
            "profit-target / time-exit, and press **Arm** — it enters and exits automatically. "
            "(Step 4 is only for manual one-off testing.)"
        )

    la1, la2, la3 = st.columns(3)
    with la1:
        live_mode = st.toggle(
            "Enable LIVE mode", value=False, key="live_algo_mode",
            help="Keep OFF for paper / dry-run. Turn ON only when you intend to place real orders.")
    with la2:
        broker_name = st.selectbox(
            "🔴 Broker",
            ["Groww", "Zerodha", "Upstox", "Angel One", "Dhan", "Other"],
            key="live_algo_broker")
    with la3:
        symbol_live = st.selectbox("🔴 Symbol", ["NIFTY", "BANKNIFTY", "FINNIFTY"], key="live_algo_symbol")

    adapter = get_live_broker_adapter(broker_name)

    lot_size_live = int(cfg.get("data", {}).get("lot_sizes", {}).get(symbol_live, 1) or 1)
    st.caption(f"Configured lot size for {symbol_live}: {lot_size_live}")

    st.subheader("Step 1 · 🔴 Broker Connection")
    st.caption("Provide credentials via environment variables, or use the manual / token helpers below.")
    env_vars = adapter.required_env_vars()
    env_values = {k: os.getenv(k, "") for k in env_vars}
    env_ready = all(bool(v) for v in env_values.values())
    ec1, ec2 = st.columns([2, 3])
    with ec1:
        st.metric("Env Credential Status", "Ready" if env_ready else "Missing")
    with ec2:
        st.write({k: _mask_secret(v) for k, v in env_values.items()})

    with st.expander("Manual session credentials (optional — if env vars are not set)", expanded=False):
        manual_api_key = st.text_input("API Key", value="", key="live_algo_api_key")
        manual_access_token = st.text_input("Access Token", value="", type="password", key="live_algo_access_token")
        manual_ready = bool(manual_api_key and manual_access_token)
        if manual_ready:
            st.success("Manual session credentials present for this run.")
        else:
            st.info("Provide API key + access token if env vars are not set.")

    with st.expander("Advanced: Generate Access Token (Groww key+secret / TOTP)", expanded=False):
        st.caption(
            "Mints a daily Groww access token. Requires API key + secret (env or "
            "below). A real network call runs only when 'Allow live token call' is on."
        )
        mt_key = st.text_input("API Key (mint)", value="", key="live_algo_mint_key")
        mt_secret = st.text_input("API Secret (mint)", value="", type="password", key="live_algo_mint_secret")
        mt_type = st.selectbox("Auth flow", ["approval", "totp"], key="live_algo_mint_type")
        mt_totp = st.text_input("TOTP (if totp flow)", value="", key="live_algo_mint_totp")
        mt_allow_live = st.checkbox("Allow live token call", value=False, key="live_algo_mint_allow_live")
        if st.button("🔑 Generate Access Token", key="live_algo_mint_btn"):
            if broker_name != "Groww":
                st.error("Token mint is implemented for Groww only.")
            elif not (mt_key and mt_secret):
                st.error("API key and secret are required to mint a token.")
            else:
                _mint_adapter = get_live_broker_adapter(
                    "Groww", api_key=mt_key, api_secret=mt_secret, allow_live=bool(mt_allow_live)
                )
                _mres = _mint_adapter.mint_access_token(
                    key_type=mt_type, totp=mt_totp.strip(), allow_live=bool(mt_allow_live)
                )
                if _mres.get("ok") and _mres.get("has_token"):
                    st.success("Access token minted. Paste it into the Access Token field above to use it.")
                elif _mres.get("ok"):
                    st.info(str(_mres.get("message", "Token request built (dry-run).")))
                else:
                    st.error(str(_mres.get("message", "Token mint failed.")))
                append_journal_event({
                    "event": "token_mint",
                    "broker": broker_name,
                    "flow": mt_type,
                    "allow_live": bool(mt_allow_live),
                    "ok": bool(_mres.get("ok")),
                    "has_token": bool(_mres.get("has_token")),
                    "message": _mres.get("message"),
                })

    creds_ready = adapter.credentials_ready(env_values, manual_ready=manual_ready)

    with st.expander("Advanced: Groww Instruments Master (for exact trading symbols)", expanded=False):
        from pathlib import Path as _Path
        from src.groww_instruments import download_instruments, resolve_trading_symbol
        _inst_path = "data/groww_instruments.csv"
        _cached = _Path(_inst_path).exists()
        st.write(f"Cache present: {'✅ Yes' if _cached else '❌ No'} ({_inst_path})")
        if st.button("⬇️ Download / Refresh Instruments CSV", key="live_algo_refresh_instruments"):
            with st.spinner("Downloading instruments master..."):
                _dl = download_instruments(_inst_path)
            if _dl.get("ok"):
                st.success(f"{_dl.get('message')} ({_dl.get('bytes', 0):,} bytes)")
            else:
                st.error(str(_dl.get("message", "Download failed.")))
        st.caption(
            "Trading symbols for live legs are resolved from this file. Without it, "
            "a best-effort composed symbol is used and must not be sent live."
        )

    # Rebuild adapter with resolved credentials so broker transport can use them.
    # allow_live stays False here; real transmission is gated later by dry-run + confirm.
    resolved_api_key = manual_api_key or env_values.get("GROWW_API_KEY", "") or env_values.get("BROKER_API_KEY", "")
    resolved_api_secret = env_values.get("GROWW_API_SECRET", "") or env_values.get("BROKER_API_SECRET", "")
    resolved_access_token = manual_access_token or env_values.get("GROWW_ACCESS_TOKEN", "") or env_values.get("BROKER_ACCESS_TOKEN", "")
    adapter = get_live_broker_adapter(
        broker_name,
        api_key=resolved_api_key,
        api_secret=resolved_api_secret,
        access_token=resolved_access_token,
        allow_live=False)

    st.divider()

    st.subheader("Step 2 · 🔴 Strategy & Strikes")
    st.caption("Pick a strategy, set the expiry, and enter all strike prices — every strike field is required.")
    sb1, sb2, sb3, sb4 = st.columns(4)
    with sb1:
        strategy_live = st.selectbox(
            "🔴 Strategy",
            [
                "Iron Condor (Defined Risk)",
                "Bull Put Spread",
                "Bear Call Spread",
                "Short Strangle",
                "Long Call",
                "Long Put",
            ],
            key="live_algo_strategy")
    with sb2:
        lots_live = st.number_input("🔴 Lots", min_value=1, max_value=50, value=1, key="live_algo_lots")
    with sb3:
        expiry_live = st.text_input("🔴 Expiry (YYYY-MM-DD)", value="", key="live_algo_expiry",
                                    placeholder="2026-07-30")
    with sb4:
        entry_ref_live = st.number_input("Entry reference value (optional)", min_value=0.0, value=0.0, step=0.05, key="live_algo_entry_ref")

    strike_inputs = {}
    if strategy_live == "Iron Condor (Defined Risk)":
        s1, s2, s3, s4 = st.columns(4)
        strike_inputs["buy_pe"] = s1.number_input("Buy PE", min_value=1000, step=50, value=23500, key="la_buy_pe")
        strike_inputs["sell_pe"] = s2.number_input("Sell PE", min_value=1000, step=50, value=23800, key="la_sell_pe")
        strike_inputs["sell_ce"] = s3.number_input("Sell CE", min_value=1000, step=50, value=24200, key="la_sell_ce")
        strike_inputs["buy_ce"] = s4.number_input("Buy CE", min_value=1000, step=50, value=24500, key="la_buy_ce")
    elif strategy_live == "Bull Put Spread":
        s1, s2 = st.columns(2)
        strike_inputs["sell_pe"] = s1.number_input("Sell PE", min_value=1000, step=50, value=23800, key="la_bps_sell_pe")
        strike_inputs["buy_pe"] = s2.number_input("Buy PE", min_value=1000, step=50, value=23550, key="la_bps_buy_pe")
    elif strategy_live == "Bear Call Spread":
        s1, s2 = st.columns(2)
        strike_inputs["sell_ce"] = s1.number_input("Sell CE", min_value=1000, step=50, value=24200, key="la_bcs_sell_ce")
        strike_inputs["buy_ce"] = s2.number_input("Buy CE", min_value=1000, step=50, value=24450, key="la_bcs_buy_ce")
    elif strategy_live == "Short Strangle":
        s1, s2 = st.columns(2)
        strike_inputs["sell_pe"] = s1.number_input("Sell PE", min_value=1000, step=50, value=23800, key="la_ss_sell_pe")
        strike_inputs["sell_ce"] = s2.number_input("Sell CE", min_value=1000, step=50, value=24200, key="la_ss_sell_ce")
    elif strategy_live == "Long Call":
        strike_inputs["buy_ce"] = st.number_input("Buy CE", min_value=1000, step=50, value=24200, key="la_lc_buy_ce")
    else:
        strike_inputs["buy_pe"] = st.number_input("Buy PE", min_value=1000, step=50, value=23800, key="la_lp_buy_pe")

    live_legs = _build_live_legs(strategy_live, strike_inputs)
    units_per_leg = int(lots_live) * lot_size_live
    legs_df = pd.DataFrame([
        {
            "Action": leg["action"],
            "Type": leg["option_type"],
            "Strike": int(leg["strike"]),
            "Units": units_per_leg,
        }
        for leg in live_legs
    ])
    st.dataframe(legs_df, hide_index=True)

    margin_info = adapter.estimate_margin_proxy(
        strategy_live,
        live_legs,
        lot_size_live,
        int(lots_live),
        float(entry_ref_live))
    st.caption(
        f"Margin proxy ({margin_info['model']}): ₹{float(margin_info['proxy_margin']):,.0f} "
        "(final broker blocked margin may differ)."
    )

    st.subheader("Step 3 · 🔴 Risk Limits")
    st.caption("Stop-Loss and Target are required and must be greater than 0. Time exit and daily cap have safe defaults.")
    rg1, rg2, rg3, rg4 = st.columns(4)
    with rg1:
        sl_live = st.number_input("🔴 Stop-Loss value", min_value=0.0, value=0.0, step=0.05, key="live_algo_sl")
    with rg2:
        tgt_live = st.number_input("🔴 Target value", min_value=0.0, value=0.0, step=0.05, key="live_algo_target")
    with rg3:
        time_exit_live = st.number_input("Time exit (minutes)", min_value=5, max_value=600, value=120, key="live_algo_time_exit")
    with rg4:
        daily_cutoff_live = st.number_input("Daily max loss (₹)", min_value=1000.0, value=15000.0, step=500.0, key="live_algo_daily_cutoff")

    st.subheader("Step 4 · Manual Execution (one-off testing — optional)")
    st.caption("Optional manual path. For hands-off trading use the Automated Auto-Trader at the bottom instead.")
    dry_run_orders = st.toggle("Dry-run orders (recommended)", value=True, key="live_algo_dry_run_orders")
    session_token_for_check = os.getenv(env_vars[0], "") if env_vars else ""
    access_token_for_check = os.getenv(env_vars[-1], "") if env_vars else ""
    if manual_ready:
        session_token_for_check = manual_api_key
        access_token_for_check = manual_access_token

    sx1, sx2 = st.columns(2)
    with sx1:
        if st.button("🔐 Check Broker Session", key="live_algo_session_check"):
            sess = adapter.check_session(session_token_for_check, access_token_for_check)
            if sess.get("ok"):
                st.success(str(sess.get("message", "Session check passed.")))
            else:
                st.error(str(sess.get("message", "Session check failed.")))
            append_journal_event({
                "event": "session_check",
                "broker": broker_name,
                "symbol": symbol_live,
                "result": sess,
            })
    with sx2:
        status_intent_id = st.text_input("Intent ID (status lookup)", value="", key="live_algo_status_intent_id")
        if st.button("📡 Check Intent Status", key="live_algo_check_status"):
            status_res = adapter.get_order_status(status_intent_id.strip())
            if status_res.get("ok"):
                st.info(str(status_res.get("message", "Status fetched.")))
            else:
                st.error(str(status_res.get("message", "Status lookup failed.")))
            append_journal_event({
                "event": "intent_status_lookup",
                "broker": broker_name,
                "symbol": symbol_live,
                "intent_id": status_intent_id.strip(),
                "result": status_res,
            })

    st.markdown("**Pre-Flight Checklist**")
    from pathlib import Path as _PathPF
    _instr_ready = _PathPF("data/groww_instruments.csv").exists()
    _token_ready = bool(resolved_access_token)
    _checks = {
        "Broker credentials present": bool(creds_ready),
        "Access token available": _token_ready,
        "Instruments cache present": _instr_ready,
        "Expiry set": bool(expiry_live and expiry_live.strip()),
        "SL & Target > 0": (float(sl_live) > 0 and float(tgt_live) > 0),
        "Legs configured": bool(live_legs),
        "Dry Run Validation passed": bool(st.session_state.get("live_algo_last_dryrun_ok")),
        "Kill-switch disarmed": not bool(st.session_state.get("live_algo_kill_switch")),
        "Live mode ON": bool(live_mode),
    }
    _pf_cols = st.columns(3)
    for _i, (_label, _ok) in enumerate(_checks.items()):
        with _pf_cols[_i % 3]:
            st.markdown(f"{'✅' if _ok else '❌'} {_label}")
    preflight_ok = all(_checks.values())
    if preflight_ok:
        st.success("All pre-flight checks green. START LIVE is unlocked.")
    else:
        _pending = [k for k, v in _checks.items() if not v]
        st.warning("START LIVE locked. Pending: " + " | ".join(_pending))

    confirm_text = st.text_input("Type START LIVE to confirm", value="", key="live_algo_confirm_text")
    ex1, ex2, ex3 = st.columns(3)
    with ex1:
        if st.button("🧪 Dry Run Validation", key="live_algo_dry_run"):
            issues = []
            if not expiry_live:
                issues.append("Expiry is empty")
            if float(sl_live) <= 0 or float(tgt_live) <= 0:
                issues.append("SL/Target must be > 0")
            if not creds_ready:
                issues.append("Broker credentials are missing")
            if st.session_state.get("live_algo_kill_switch"):
                issues.append("Kill-switch is armed")

            st.session_state["live_algo_last_dryrun_ok"] = len(issues) == 0
            if issues:
                st.error("Dry run failed: " + " | ".join(issues))
                append_journal_event({
                    "event": "dry_run_failed",
                    "broker": broker_name,
                    "symbol": symbol_live,
                    "strategy": strategy_live,
                    "issues": issues,
                })
            else:
                st.success("Dry run passed. Strategy preview and controls are valid.")
                append_journal_event({
                    "event": "dry_run_passed",
                    "broker": broker_name,
                    "symbol": symbol_live,
                    "strategy": strategy_live,
                    "lots": int(lots_live),
                    "units_per_leg": int(units_per_leg),
                })
    with ex2:
        if st.button("▶ Start Algo", key="live_algo_start"):
            if st.session_state.get("live_algo_kill_switch"):
                st.error("Kill-switch is armed. Disarm first.")
            elif not live_mode:
                st.error("Live mode is OFF. Enable LIVE mode first to start execution.")
            elif not preflight_ok:
                st.error("Pre-flight checklist is not all-green. Resolve pending items first.")
            elif confirm_text.strip() != "START LIVE":
                st.error("Confirmation text mismatch. Type START LIVE exactly.")
            elif not st.session_state.get("live_algo_last_dryrun_ok"):
                st.error("Run a successful Dry Run Validation first.")
            elif not creds_ready:
                st.error("Broker credentials missing. Set env vars or manual session credentials.")
            else:
                req = StartAlgoRequest(
                    broker=broker_name,
                    symbol=symbol_live,
                    strategy=strategy_live,
                    lots=int(lots_live),
                    lot_size=int(lot_size_live),
                    expiry=expiry_live.strip(),
                    legs=live_legs,
                    stop_loss=float(sl_live),
                    target=float(tgt_live),
                    time_exit_minutes=int(time_exit_live),
                    daily_max_loss_inr=float(daily_cutoff_live))
                start_result = adapter.place_basket_order(req, dry_run=bool(dry_run_orders))
                if start_result.get("ok"):
                    st.info(str(start_result.get("message", "Order request captured.")))
                    _intent_id = start_result.get("intent_id")
                    append_journal_event({
                        "event": "basket_order_requested",
                        "broker": broker_name,
                        "symbol": symbol_live,
                        "strategy": strategy_live,
                        "intent_id": _intent_id,
                        "payload": start_result.get("payload"),
                        "dry_run": bool(dry_run_orders),
                    })
                    # Persist open live-position run-state for recovery/polling.
                    upsert_live_position(_intent_id, {
                        "broker": broker_name,
                        "symbol": symbol_live,
                        "strategy": strategy_live,
                        "lots": int(lots_live),
                        "units_per_leg": int(units_per_leg),
                        "expiry": expiry_live.strip(),
                        "dry_run": bool(dry_run_orders),
                        "status": "requested",
                        "last_status": start_result.get("transport", {}).get("message"),
                        "leg_refs": start_result.get("leg_refs", []),
                    })
                else:
                    st.error(str(start_result.get("message", "Start request failed.")))
                    append_journal_event({
                        "event": "basket_order_rejected",
                        "broker": broker_name,
                        "symbol": symbol_live,
                        "strategy": strategy_live,
                        "reason": start_result.get("message"),
                    })
    with ex3:
        if st.button("🛑 Emergency Stop", key="live_algo_stop"):
            st.session_state["live_algo_kill_switch"] = True
            st.error("Kill-switch armed. Start is blocked until disarmed.")
            append_journal_event({
                "event": "kill_switch_armed",
                "broker": broker_name,
                "symbol": symbol_live,
                "strategy": strategy_live,
            })

    if st.button("⏹️ Square-off Intent", key="live_algo_squareoff"):
        sq = adapter.square_off_all(symbol_live, strategy_live)
        if sq.get("ok"):
            st.warning(str(sq.get("message", "Square-off intent captured.")))
        else:
            st.error(str(sq.get("message", "Square-off failed.")))
        append_journal_event({
            "event": "square_off_intent",
            "broker": broker_name,
            "symbol": symbol_live,
            "strategy": strategy_live,
            "result": sq,
        })

    disarm = st.button("✅ Disarm Kill-Switch", key="live_algo_disarm")
    if disarm:
        st.session_state["live_algo_kill_switch"] = False
        st.success("Kill-switch disarmed.")
        append_journal_event({
            "event": "kill_switch_disarmed",
            "broker": broker_name,
            "symbol": symbol_live,
            "strategy": strategy_live,
        })

    st.divider()
    st.subheader("📊 Monitor · Live Audit Snapshot (read-only)")
    st.code(
        {
            "mode": "LIVE" if live_mode else "PAPER",
            "broker": broker_name,
            "symbol": symbol_live,
            "strategy": strategy_live,
            "lots": int(lots_live),
            "units_per_leg": int(units_per_leg),
            "expiry": expiry_live,
            "stop_loss": float(sl_live),
            "target": float(tgt_live),
            "time_exit_minutes": int(time_exit_live),
            "daily_max_loss_inr": float(daily_cutoff_live),
            "credentials_ready": bool(creds_ready),
            "dry_run_ok": bool(st.session_state.get("live_algo_last_dryrun_ok")),
            "kill_switch": bool(st.session_state.get("live_algo_kill_switch")),
            "margin_proxy_inr": float(margin_info["proxy_margin"]),
            "status": "Scaffold only - no live order transmission",
        },
        language="json")

    st.divider()
    st.subheader("📊 Monitor · Open Positions")
    _positions = load_live_positions()
    if _positions:
        _pos_rows = list(_positions.values())
        st.dataframe(pd.DataFrame(_pos_rows), hide_index=True)

        pcol1, pcol2 = st.columns([2, 3])
        with pcol1:
            if st.button("🔄 Poll All Open Positions", key="live_algo_poll_all"):
                polled = 0
                for _iid, _pos in list(_positions.items()):
                    # Reconcile each leg by its broker order id when available.
                    _leg_status = []
                    for _lr in (_pos.get("leg_refs") or []):
                        _oid = _lr.get("groww_order_id") or _lr.get("ref_id")
                        if not _oid:
                            continue
                        _lres = adapter.get_order_status(_oid)
                        _leg_status.append({
                            "order_id": _oid,
                            "ok": bool(_lres.get("ok")),
                            "message": _lres.get("message"),
                        })
                    # Fall back to intent-level status if no leg refs.
                    _sres = adapter.get_order_status(_iid) if not _leg_status else {
                        "ok": all(s["ok"] for s in _leg_status),
                        "message": f"Reconciled {len(_leg_status)} leg(s).",
                    }
                    upsert_live_position(_iid, {
                        "status": "polled",
                        "last_status": _sres.get("message"),
                        "last_poll_ok": bool(_sres.get("ok")),
                        "leg_status": _leg_status,
                    })
                    append_journal_event({
                        "event": "position_poll",
                        "broker": broker_name,
                        "symbol": symbol_live,
                        "intent_id": _iid,
                        "leg_status": _leg_status,
                        "result": _sres,
                    })
                    polled += 1
                st.success(f"Polled {polled} open position(s). Status persisted to run-state.")
                st.rerun()
        with pcol2:
            _close_iid = st.selectbox(
                "Close/remove position (intent id)",
                list(_positions.keys()),
                key="live_algo_close_iid")
            if st.button("❌ Close & Remove Position", key="live_algo_close_pos"):
                _sq = adapter.square_off_all(symbol_live, strategy_live)
                remove_live_position(_close_iid)
                append_journal_event({
                    "event": "position_closed",
                    "broker": broker_name,
                    "symbol": symbol_live,
                    "intent_id": _close_iid,
                    "result": _sq,
                })
                st.warning(f"Position {_close_iid} squared-off and removed from run-state.")
                st.rerun()
    else:
        st.info("No open live positions tracked.")

    st.divider()
    st.subheader("📊 Monitor · Execution Journal (last 20 events)")
    _jrows = tail_journal(limit=20)
    if _jrows:
        st.dataframe(pd.DataFrame(_jrows), hide_index=True)
    else:
        st.info("No live execution events yet.")

    st.divider()
    st.subheader("🤖 Automated Auto-Trader — Entry & Exit (paper-trade logic)")
    st.caption(
        "**This is the main purpose of the tab.** Arms an always-on loop that AUTO-ENTERS the "
        "strategy from Steps 1–3 and AUTO-EXITS using the same rules as the paper-trade engine: "
        "fixed max-loss, profit-target, or time limit (plus a daily loss cutoff). Real orders "
        "transmit only when **Allow live** is ON and **Dry-run** is OFF; otherwise it simulates."
    )

    _auto_cfg = load_auto_config()
    ar1, ar2, ar3 = st.columns(3)
    with ar1:
        auto_max_loss = st.number_input(
            "Max loss (₹)", min_value=0.0, value=float(_auto_cfg.get("max_loss_inr", 3000.0)),
            step=250.0, key="auto_max_loss")
    with ar2:
        auto_target = st.number_input(
            "Profit target (₹)", min_value=0.0, value=float(_auto_cfg.get("target_profit_inr", 2000.0)),
            step=250.0, key="auto_target")
    with ar3:
        auto_time_exit = st.number_input(
            "Time exit (min)", min_value=0, value=int(_auto_cfg.get("time_exit_minutes", 180)),
            step=15, key="auto_time_exit")

    ar4, ar5, ar6 = st.columns(3)
    with ar4:
        auto_daily_loss = st.number_input(
            "Daily max loss (₹)", min_value=0.0, value=float(_auto_cfg.get("daily_max_loss_inr", 6000.0)),
            step=500.0, key="auto_daily_loss")
    with ar5:
        auto_win_start = st.text_input("Window start", value=str(_auto_cfg.get("trade_window_start", "09:20")), key="auto_win_start")
    with ar6:
        auto_win_end = st.text_input("Window end", value=str(_auto_cfg.get("trade_window_end", "15:20")), key="auto_win_end")

    ar7, ar8, ar9 = st.columns(3)
    with ar7:
        auto_interval = st.number_input(
            "Poll interval (sec)", min_value=5, value=int(_auto_cfg.get("poll_interval_sec", 30)),
            step=5, key="auto_interval")
    with ar8:
        auto_dry_run = st.checkbox("Dry-run (simulate)", value=bool(_auto_cfg.get("dry_run", True)), key="auto_dry_run")
    with ar9:
        auto_allow_live = st.checkbox("Allow live transmit", value=bool(_auto_cfg.get("allow_live", False)), key="auto_allow_live")

    _is_armed = bool(_auto_cfg.get("armed"))
    st.info(f"Current state: **{'🟢 ARMED' if _is_armed else '⚪ DISARMED'}** "
            f"| dry_run={_auto_cfg.get('dry_run', True)} | allow_live={_auto_cfg.get('allow_live', False)}")

    def _snapshot_auto_cfg(armed: bool) -> dict:
        return {
            "armed": armed,
            "broker": st.session_state.get("live_algo_broker", "Groww") if "live_algo_broker" in st.session_state else _auto_cfg.get("broker", "Groww"),
            "symbol": "NIFTY",
            "strategy": strategy_live,
            "expiry": str(expiry_live),
            "lots": int(lots_live),
            "lot_size": int(lot_size_live),
            "legs": [
                {"action": leg["action"], "option_type": leg["option_type"], "strike": int(leg["strike"])}
                for leg in live_legs
            ],
            "max_loss_inr": float(auto_max_loss),
            "target_profit_inr": float(auto_target),
            "time_exit_minutes": int(auto_time_exit),
            "daily_max_loss_inr": float(auto_daily_loss),
            "trade_window_start": str(auto_win_start),
            "trade_window_end": str(auto_win_end),
            "poll_interval_sec": int(auto_interval),
            "dry_run": bool(auto_dry_run),
            "allow_live": bool(auto_allow_live),
        }

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("🟢 Arm Auto-Runner", key="auto_arm_btn"):
            if not live_legs:
                st.error("Configure strategy legs above first.")
            else:
                save_auto_config(_snapshot_auto_cfg(True))
                st.success("Auto-runner ARMED. Start the loop: `python -m src.live_auto_runner --loop`")
                st.rerun()
    with b2:
        if st.button("⚪ Disarm", key="auto_disarm_btn"):
            _cfg = load_auto_config()
            _cfg["armed"] = False
            save_auto_config(_cfg)
            st.warning("Auto-runner DISARMED.")
            st.rerun()
    with b3:
        if st.button("▶ Run Single Tick Now", key="auto_tick_btn"):
            save_auto_config(_snapshot_auto_cfg(_is_armed))
            _res = LiveAutoTrader().tick()
            st.json(_res)

    st.caption(
        "For unattended operation, run the loop in a terminal (survives Streamlit reruns):\n\n"
        "`python -m src.live_auto_runner --loop`"
    )


# ============================================================
#  TAB 14 — Auto Algo Trader (unified: real-time data + auto entry/exit)
# ============================================================

with tab14:
    st.header("🤖 Auto Algo Trader")
    st.caption(
        "One place to run a fully automatic options algo: reads market data in **real time** "
        "(no cron), enters and exits using the paper-trade logic, across any configured broker. "
        "Fields marked 🔴 are mandatory. Keep **Dry-run ON** until your setup is verified."
    )

    _acfg = load_algo_config()
    _ctrl = _acfg.get("controls", {})
    _trd = _acfg.get("trading", {})
    _rsk = _acfg.get("risk", {})

    # ── Live state banner ──
    _mode_txt = "🟢 ARMED" if _ctrl.get("armed") else "⚪ DISARMED"
    _live_txt = "🔴 LIVE ORDERS" if (_ctrl.get("allow_live") and not _ctrl.get("dry_run")) else "🧪 DRY-RUN"
    st.info(f"State: **{_mode_txt}**  |  **{_live_txt}**  |  Broker: **{_acfg.get('active_broker','Groww')}**  |  "
            f"Strategy: {_trd.get('strategy','—')}")

    # ── Section A · Broker & Credentials ──
    st.subheader("A · 🔴 Broker & Credentials")
    st.caption("Credentials are saved to `algo_trade_config.json` (git-ignored). Blank fields fall back to environment variables.")
    _broker_list = list(SUPPORTED_BROKERS)
    _active_idx = _broker_list.index(_acfg.get("active_broker", "Groww")) if _acfg.get("active_broker", "Groww") in _broker_list else 0
    aa1, aa2 = st.columns([2, 3])
    with aa1:
        aa_broker = st.selectbox("🔴 Active broker", _broker_list, index=_active_idx, key="aat_broker")
    _bcreds = (_acfg.get("brokers", {}) or {}).get(aa_broker, {}) or {}
    _resolved = resolve_broker_creds(_acfg, aa_broker)
    with aa2:
        st.write({
            "api_key": mask_secret(_resolved.get("api_key", "")),
            "api_secret": mask_secret(_resolved.get("api_secret", "")),
            "access_token": mask_secret(_resolved.get("access_token", "")),
        })

    with st.expander("Edit credentials for the selected broker", expanded=not bool(_resolved.get("api_key"))):
        ac1, ac2 = st.columns(2)
        with ac1:
            aa_key = st.text_input("API Key", value=_bcreds.get("api_key", ""), type="password", key="aat_api_key")
            aa_secret = st.text_input("API Secret", value=_bcreds.get("api_secret", ""), type="password", key="aat_api_secret")
        with ac2:
            aa_token = st.text_input("Access Token (auto-filled on regenerate)", value=_bcreds.get("access_token", ""), type="password", key="aat_access_token")
            aa_flow = st.selectbox("Auth flow", ["approval", "totp"], index=0 if _bcreds.get("auth_flow", "approval") == "approval" else 1, key="aat_auth_flow")
            aa_totp = st.text_input("TOTP (only for totp flow)", value=_bcreds.get("totp", ""), key="aat_totp")
        if st.button("💾 Save Credentials", key="aat_save_creds"):
            _acfg.setdefault("brokers", {}).setdefault(aa_broker, {})
            _acfg["brokers"][aa_broker].update({
                "api_key": aa_key, "api_secret": aa_secret, "access_token": aa_token,
                "auth_flow": aa_flow, "totp": aa_totp,
            })
            _acfg["active_broker"] = aa_broker
            save_algo_config(_acfg)
            st.success(f"Credentials saved for {aa_broker}.")
            st.rerun()

    tk1, tk2 = st.columns([1, 2])
    with tk1:
        aa_regen_live = st.checkbox("Allow live token call", value=False, key="aat_regen_live")
    with tk2:
        if st.button("🔑 Regenerate Access Token", key="aat_regen_btn"):
            _acfg["active_broker"] = aa_broker
            save_algo_config(_acfg)
            _tres = regenerate_token(aa_broker, allow_live=bool(aa_regen_live), cfg=load_algo_config())
            (st.success if _tres.get("ok") else st.error)(_tres.get("message"))
            st.rerun()

    st.divider()

    # ── Section B · Strategy & Strikes ──
    st.subheader("B · 🔴 Strategy & Strikes")
    _symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
    bb1, bb2, bb3, bb4 = st.columns(4)
    with bb1:
        aa_symbol = st.selectbox("🔴 Symbol", _symbols,
                                 index=_symbols.index(_trd.get("symbol", "NIFTY")) if _trd.get("symbol", "NIFTY") in _symbols else 0,
                                 key="aat_symbol")
    _strats = ["Iron Condor (Defined Risk)", "Bull Put Spread", "Bear Call Spread", "Short Strangle", "Long Call", "Long Put"]
    with bb2:
        aa_strategy = st.selectbox("🔴 Strategy", _strats,
                                   index=_strats.index(_trd.get("strategy")) if _trd.get("strategy") in _strats else 0,
                                   key="aat_strategy")
    with bb3:
        aa_lots = st.number_input("🔴 Lots", min_value=1, max_value=50, value=int(_trd.get("lots", 1)), key="aat_lots")
    with bb4:
        aa_expiry = st.text_input("🔴 Expiry (YYYY-MM-DD)", value=str(_trd.get("expiry", "")), placeholder="2026-07-30", key="aat_expiry")

    _aa_lot_size = int(cfg.get("data", {}).get("lot_sizes", {}).get(aa_symbol, 65) or 65)
    st.caption(f"Lot size for {aa_symbol}: {_aa_lot_size}")

    _st = _trd.get("strikes", {})
    # Helper: return config value only if valid (>=1000); otherwise use the default.
    # Prevents crashes when config has 0/None (e.g. after clearing hardcoded strikes).
    def _sv(key, default):
        v = int(_st.get(key, 0) or 0)
        return v if v >= 1000 else default

    st.markdown("**🔴 Strikes** (all shown fields are required)")
    if aa_strategy == "Iron Condor (Defined Risk)":
        s1, s2, s3, s4 = st.columns(4)
        aa_buy_pe  = s1.number_input("Buy PE",  min_value=1000, step=50, value=_sv("buy_pe",  23500), key="aat_buy_pe")
        aa_sell_pe = s2.number_input("Sell PE", min_value=1000, step=50, value=_sv("sell_pe", 23800), key="aat_sell_pe")
        aa_sell_ce = s3.number_input("Sell CE", min_value=1000, step=50, value=_sv("sell_ce", 24200), key="aat_sell_ce")
        aa_buy_ce  = s4.number_input("Buy CE",  min_value=1000, step=50, value=_sv("buy_ce",  24500), key="aat_buy_ce")
    elif aa_strategy == "Bull Put Spread":
        s1, s2 = st.columns(2)
        aa_sell_pe = s1.number_input("Sell PE", min_value=1000, step=50, value=_sv("sell_pe", 23800), key="aat_bps_sell_pe")
        aa_buy_pe  = s2.number_input("Buy PE",  min_value=1000, step=50, value=_sv("buy_pe",  23550), key="aat_bps_buy_pe")
        aa_sell_ce = _sv("sell_ce", 24200); aa_buy_ce = _sv("buy_ce", 24500)
    elif aa_strategy == "Bear Call Spread":
        s1, s2 = st.columns(2)
        aa_sell_ce = s1.number_input("Sell CE", min_value=1000, step=50, value=_sv("sell_ce", 24200), key="aat_bcs_sell_ce")
        aa_buy_ce  = s2.number_input("Buy CE",  min_value=1000, step=50, value=_sv("buy_ce",  24450), key="aat_bcs_buy_ce")
        aa_sell_pe = _sv("sell_pe", 23800); aa_buy_pe = _sv("buy_pe", 23500)
    elif aa_strategy == "Short Strangle":
        s1, s2 = st.columns(2)
        aa_sell_pe = s1.number_input("Sell PE", min_value=1000, step=50, value=_sv("sell_pe", 23800), key="aat_ss_sell_pe")
        aa_sell_ce = s2.number_input("Sell CE", min_value=1000, step=50, value=_sv("sell_ce", 24200), key="aat_ss_sell_ce")
        aa_buy_pe = _sv("buy_pe", 23500); aa_buy_ce = _sv("buy_ce", 24500)
    elif aa_strategy == "Long Call":
        aa_buy_ce  = st.number_input("Buy CE",  min_value=1000, step=50, value=_sv("buy_ce",  24200), key="aat_lc_buy_ce")
        aa_buy_pe  = _sv("buy_pe", 23500); aa_sell_pe = _sv("sell_pe", 23800); aa_sell_ce = _sv("sell_ce", 24200)
    else:  # Long Put
        aa_buy_pe  = st.number_input("Buy PE",  min_value=1000, step=50, value=_sv("buy_pe",  23800), key="aat_lp_buy_pe")
        aa_sell_pe = _sv("sell_pe", 23800); aa_sell_ce = _sv("sell_ce", 24200); aa_buy_ce = _sv("buy_ce", 24500)

    _aa_strikes = {"buy_pe": int(aa_buy_pe), "sell_pe": int(aa_sell_pe), "sell_ce": int(aa_sell_ce), "buy_ce": int(aa_buy_ce)}
    _aa_legs = build_legs(aa_strategy, _aa_strikes)
    st.dataframe(pd.DataFrame([
        {"Action": l["action"], "Type": l["option_type"], "Strike": l["strike"], "Units": int(aa_lots) * _aa_lot_size}
        for l in _aa_legs
    ]), hide_index=True)

    tw1, tw2, tw3, tw4 = st.columns(4)
    with tw1:
        aa_win_start = st.text_input("Window start", value=str(_trd.get("trade_window_start", "09:20")), key="aat_win_start")
    with tw2:
        aa_win_end = st.text_input("Window end", value=str(_trd.get("trade_window_end", "15:20")), key="aat_win_end")
    with tw3:
        aa_hard_sq = st.text_input("Hard square-off", value=str(_trd.get("hard_squareoff_time", "15:20")), key="aat_hard_sq")
    with tw4:
        aa_interval = st.number_input("Poll interval (s)", min_value=5, value=int(_trd.get("poll_interval_sec", 30)), step=5, key="aat_interval")
    aa_value_snapshot = st.checkbox(
        "Value positions from live snapshot (no shared-CSV round-trip)",
        value=bool(_trd.get("value_from_snapshot", False)), key="aat_value_snapshot",
        help="When on, the auto-trader prices legs directly from the fresh in-memory market "
             "snapshot instead of the shared CSV files. Falls back to CSV if a strike LTP is missing.")
    aa_value_broker = st.checkbox(
        "Value positions from broker live LTP (live sessions only)",
        value=bool(_trd.get("value_from_broker", False)), key="aat_value_broker",
        help="When on, prices legs from the broker's live-data LTP API (most accurate — matches "
             "your fills). Only works in a live session (allow-live + token); otherwise falls back "
             "to snapshot, then CSV.")

    st.divider()

    # ── Section C · Risk Controls ──
    st.subheader("C · 🔴 Risk Controls (loss protection)")
    st.caption("These caps protect you during sudden crashes / rallies and cap daily damage.")
    rc1, rc2, rc3 = st.columns(3)
    with rc1:
        aa_target = st.number_input("🔴 Profit target / trade (₹)", min_value=0.0, value=float(_rsk.get("target_profit_inr", 2000.0)), step=250.0, key="aat_target")
        aa_ptml = st.number_input("🔴 Max loss / trade (₹)", min_value=0.0, value=float(_rsk.get("per_trade_max_loss_inr", 3000.0)), step=250.0, key="aat_ptml")
        aa_time_exit = st.number_input("Time exit (min)", min_value=0, value=int(_rsk.get("time_exit_minutes", 180)), step=15, key="aat_time_exit")
    with rc2:
        aa_daily_loss = st.number_input("🔴 Daily max loss (₹)", min_value=0.0, value=float(_rsk.get("daily_max_loss_inr", 15000.0)), step=500.0, key="aat_daily_loss")
        aa_daily_profit = st.number_input("Daily profit lock (₹, 0=off)", min_value=0.0, value=float(_rsk.get("daily_profit_target_inr", 0.0)), step=500.0, key="aat_daily_profit")
        aa_max_amt = st.number_input("🔴 Max trade amount (₹)", min_value=0.0, value=float(_rsk.get("max_trade_amount_inr", 150000.0)), step=5000.0, key="aat_max_amt")
    with rc3:
        aa_crash = st.number_input("Crash guard (% drop)", min_value=0.0, value=float(_rsk.get("crash_guard_pct", 1.5)), step=0.1, key="aat_crash")
        aa_rally = st.number_input("Rally guard (% rise)", min_value=0.0, value=float(_rsk.get("rally_guard_pct", 1.5)), step=0.1, key="aat_rally")
        aa_gap = st.number_input("Gap guard (% open move)", min_value=0.0, value=float(_rsk.get("gap_guard_pct", 1.2)), step=0.1, key="aat_gap")

    rc4, rc5, rc6, rc7 = st.columns(4)
    with rc4:
        aa_max_lots = st.number_input("Max lots / trade", min_value=1, value=int(_rsk.get("max_lots_per_trade", 5)), key="aat_max_lots")
    with rc5:
        aa_max_open = st.number_input("Max open positions", min_value=1, value=int(_rsk.get("max_open_positions", 1)), key="aat_max_open")
    with rc6:
        aa_max_orders = st.number_input("Max orders / day", min_value=1, value=int(_rsk.get("max_orders_per_day", 6)), key="aat_max_orders")
    with rc7:
        aa_cooloff = st.number_input("Cool-off after loss (min)", min_value=0, value=int(_rsk.get("cooloff_after_loss_min", 30)), key="aat_cooloff")
    aa_exit_on_breach = st.checkbox("Square off open positions on crash/rally breach", value=bool(_rsk.get("exit_on_guard_breach", True)), key="aat_exit_breach")
    aa_exit_on_stale = st.checkbox(
        "Square off open positions if data feed fails (protective)",
        value=bool(_rsk.get("exit_on_stale_data", False)), key="aat_exit_stale",
        help="If the real-time feed fails, new entries are always blocked. Enable this to also "
             "square off any OPEN position when data is stale (crash/rally guard is blind without data).")

    st.divider()

    # ── Section D · Controls ──
    st.subheader("D · Run Controls")
    _sel_modes = ["manual", "auto_winner"]
    _cur_mode = _trd.get("selection_mode", "manual")
    sm1, sm2 = st.columns([1, 2])
    with sm1:
        aa_sel_mode = st.selectbox(
            "Strategy selection", _sel_modes,
            index=_sel_modes.index(_cur_mode) if _cur_mode in _sel_modes else 0,
            key="aat_sel_mode",
            help="manual = trade the fixed strategy/strikes in Section B. "
                 "auto_winner = auto-pick the best Smart (Win) strategy each entry.")
    with sm2:
        aa_enabled_strats = st.multiselect(
            "Strategies for auto_winner",
            DEFAULT_STRATEGIES,
            default=_trd.get("enabled_strategies", list(DEFAULT_STRATEGIES)),
            format_func=lambda s: STRATEGY_LABELS.get(s, s),
            key="aat_enabled_strats")
    dc1, dc2, dc3, dc4 = st.columns(4)
    with dc1:
        aa_dry_run = st.toggle("🧪 Dry-run (simulate)", value=bool(_ctrl.get("dry_run", True)), key="aat_dry_run",
                               help="ON = no real orders. Verify your setup here before going live.")
    with dc2:
        aa_allow_live = st.toggle("🔴 Allow live orders", value=bool(_ctrl.get("allow_live", False)), key="aat_allow_live",
                                  help="Real orders transmit only when this is ON and Dry-run is OFF.")
    with dc3:
        aa_auto_regen = st.checkbox("Auto-regenerate token", value=bool(_ctrl.get("auto_regenerate_token", True)), key="aat_auto_regen")
    with dc4:
        aa_stale_reconcile = st.checkbox(
            "Auto stale cleanup",
            value=bool(_ctrl.get("stale_reconciliation_enabled", True)),
            key="aat_stale_reconcile",
            help="Automatically close/remove prior-day open state records so max-open-position checks stay accurate.")

    def _aat_snapshot(armed: bool) -> dict:
        c = load_algo_config()
        c["active_broker"] = aa_broker
        c["trading"].update({
            "symbol": aa_symbol, "strategy": aa_strategy, "lots": int(aa_lots),
            "lot_size": int(_aa_lot_size), "expiry": str(aa_expiry).strip(),
            "strikes": _aa_strikes, "legs": _aa_legs,
            "selection_mode": aa_sel_mode, "enabled_strategies": list(aa_enabled_strats),
            "trade_window_start": str(aa_win_start), "trade_window_end": str(aa_win_end),
            "hard_squareoff_time": str(aa_hard_sq), "poll_interval_sec": int(aa_interval),
            "value_from_snapshot": bool(aa_value_snapshot),
            "value_from_broker": bool(aa_value_broker),
        })
        c["risk"].update({
            "target_profit_inr": float(aa_target), "per_trade_max_loss_inr": float(aa_ptml),
            "time_exit_minutes": int(aa_time_exit), "daily_max_loss_inr": float(aa_daily_loss),
            "daily_profit_target_inr": float(aa_daily_profit), "max_trade_amount_inr": float(aa_max_amt),
            "crash_guard_pct": float(aa_crash), "rally_guard_pct": float(aa_rally), "gap_guard_pct": float(aa_gap),
            "max_lots_per_trade": int(aa_max_lots), "max_open_positions": int(aa_max_open),
            "max_orders_per_day": int(aa_max_orders), "cooloff_after_loss_min": int(aa_cooloff),
            "exit_on_guard_breach": bool(aa_exit_on_breach),
            "exit_on_stale_data": bool(aa_exit_on_stale),
        })
        c["controls"].update({
            "armed": bool(armed), "dry_run": bool(aa_dry_run), "allow_live": bool(aa_allow_live),
            "auto_regenerate_token": bool(aa_auto_regen),
            "stale_reconciliation_enabled": bool(aa_stale_reconcile),
        })
        return c

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        if st.button("💾 Save Config", key="aat_save_all"):
            save_algo_config(_aat_snapshot(bool(_ctrl.get("armed"))))
            st.success("Configuration saved to algo_trade_config.json.")
            st.rerun()
    with d2:
        if st.button("🟢 Arm Trader", key="aat_arm"):
            if aa_sel_mode == "auto_winner" and not aa_enabled_strats:
                st.error("Select at least one strategy for auto_winner mode.")
            elif aa_sel_mode != "auto_winner" and any(int(l["strike"]) <= 0 for l in _aa_legs):
                st.error("Configure all strikes first.")
            elif aa_sel_mode != "auto_winner" and not str(aa_expiry).strip():
                st.error("Expiry is required before arming.")
            else:
                save_algo_config(_aat_snapshot(True))
                st.success("Armed. Start the loop in a terminal: `python -m src.algo_auto_trader --loop`")
                st.rerun()
    with d3:
        if st.button("⚪ Disarm", key="aat_disarm"):
            _c = load_algo_config(); _c["controls"]["armed"] = False; save_algo_config(_c)
            st.warning("Disarmed.")
            st.rerun()
    with d4:
        if st.button("▶ Run Single Tick", key="aat_tick"):
            save_algo_config(_aat_snapshot(bool(_ctrl.get("armed"))))
            with st.spinner("Running one tick (fetching real-time data)..."):
                _tres = AlgoAutoTrader().tick()
            st.json(_tres)

    st.caption("Unattended operation (survives app reruns): run `python -m src.algo_auto_trader --loop` in a terminal.")

    st.divider()

    # ── Section E · Real-time Market Snapshot ──
    st.subheader("E · 📈 Real-time Market Snapshot")
    # Auto-load snapshot so the tab never appears empty after app restart.
    # Refresh when symbol changes or cached snapshot is older than 60 seconds.
    _rt_key = "aat_last_rt"
    _rt_sym_key = "aat_last_rt_symbol"
    _rt_ts_key = "aat_last_rt_fetch_ts"
    _now_ts = __import__("time").time()
    _cached_rt = st.session_state.get(_rt_key)
    _cached_sym = st.session_state.get(_rt_sym_key)
    _cached_ts = float(st.session_state.get(_rt_ts_key, 0) or 0)
    _rt_age = _now_ts - _cached_ts if _cached_ts > 0 else 999999
    _needs_auto_rt = (
        _cached_rt is None
        or _cached_sym != aa_symbol
        or _rt_age > 60
    )
    if _needs_auto_rt:
        with st.spinner("Auto-loading live snapshot..."):
            _auto_rt = refresh_realtime(aa_symbol)
        st.session_state[_rt_key] = _auto_rt
        st.session_state[_rt_sym_key] = aa_symbol
        st.session_state[_rt_ts_key] = _now_ts

    if st.button("🔄 Fetch Live Snapshot", key="aat_refresh_rt"):
        with st.spinner("Fetching real-time option chain..."):
            _rt = refresh_realtime(aa_symbol)
        st.session_state["aat_last_rt"] = _rt
        st.session_state[_rt_sym_key] = aa_symbol
        st.session_state[_rt_ts_key] = __import__("time").time()
    _rt = st.session_state.get("aat_last_rt")
    if _rt and _rt.get("ok"):
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Spot", f"{_rt.get('spot', 0):,.1f}")
        m2.metric("Day move", f"{_rt.get('day_move_pct', 0):+.2f}%")
        m3.metric("Open", f"{_rt.get('open', 0):,.1f}")
        m4.metric("VIX", f"{_rt.get('vix', 0):.2f}")
        m5.metric("PCR", f"{_rt.get('pcr', 0):.2f}")
        st.caption(f"Snapshot time: {_rt.get('timestamp', '—')}")
    elif _rt:
        st.error(_rt.get("message", "Snapshot unavailable."))
    else:
        st.info("No snapshot fetched yet.")

    st.divider()

    # ── Section F · Live Status ──
    st.subheader("F · 📊 Live Status")
   
    # Auto-refresh: Show refresh button + interval selector
    _refresh_col1, _refresh_col2, _refresh_col3 = st.columns([1, 2, 2])
    with _refresh_col1:
        if st.button("🔄 Refresh Now", help="Fetch live LTPs and P&L immediately"):
            st.rerun()
    with _refresh_col2:
        _refresh_secs = st.selectbox("Auto-refresh every (sec)", [5, 10, 15, 30, 60], index=2,
                                      help="Live Status will refresh automatically at this interval")
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = 0
    with _refresh_col3:
        st.caption(f"ℹ️ LTPs update every {_refresh_secs}s during market hours")
   
    # Auto-refresh mechanism
    import time as _time_module
    _now_ts = _time_module.time()
    _should_refresh = (_now_ts - st.session_state.last_refresh) >= _refresh_secs
    if _should_refresh:
        st.session_state.last_refresh = _now_ts
   
    _fa1, _fa2 = st.columns(2)
    with _fa1:
        st.markdown("**Open positions**")
        _apos = load_live_positions()
        _aopen = {k: v for k, v in _apos.items() if str(k).startswith("algo_")}
        _total_unrealized_inr = 0.0
        _oc_for_fallback = None
        try:
            from src.auto_trade_engine import load_morning_data as _load_md_fallback
            _hist_fb, _oc_for_fallback, _pcr_fb, _vix_fb, _ocjson_fb = _load_md_fallback()
        except Exception:
            _oc_for_fallback = None

        _latest_mtm = {}
        try:
            _jpath_fb = Path("data/live_algo_journal.jsonl")
            if _jpath_fb.exists():
                for _ln_fb in _jpath_fb.read_text(encoding="utf-8").splitlines():
                    try:
                        _jr_fb = json.loads(_ln_fb)
                    except Exception:
                        continue
                    if str(_jr_fb.get("event", "")) != "auto_mark_to_market":
                        continue
                    _pid_fb = str(_jr_fb.get("position_id", "")).strip()
                    if _pid_fb:
                        _latest_mtm[_pid_fb] = _jr_fb
        except Exception:
            _latest_mtm = {}

        if _aopen:
            def _fmt_legs(legs_raw):
                """Convert legs list-of-dicts to a readable string."""
                if not legs_raw or not isinstance(legs_raw, list):
                    return "—"
                parts = []
                for leg in legs_raw:
                    action   = str(leg.get("action", "")).upper()
                    opt_type = str(leg.get("option_type", "")).upper()
                    strike   = leg.get("strike", "")
                    parts.append(f"{action} {opt_type} {strike}")
                return " | ".join(parts)

            _pos_rows = []
            for _pid, _p in _aopen.items():
                _entry_premium = float(_p.get('entry_value', 0) or 0)
                _est_amt = float(_p.get('est_amount', 0) or 0)
               
                # Fetch live LTP and calculate unrealized P&L
                _unrealized_pnl = "—"
                _current_ltp = "—"
                _unrealized_inr_num = 0.0
                _valuation_source = "—"
                try:
                    from src.live_broker_adapter import GrowwLiveBrokerAdapter
                    _broker = GrowwLiveBrokerAdapter()
                    _symbol = _p.get("symbol", "NIFTY")
                    _expiry = str(_p.get("expiry", ""))
                    _legs = _p.get("legs", [])
                   
                    if _legs and _expiry:
                        _ltps_res = _broker.get_leg_ltps(_symbol, _expiry, _legs)
                        if _ltps_res.get("ok") and _ltps_res.get("ltps"):
                            _ltps = _ltps_res.get("ltps", {})
                            # Build current position value using LTPs
                            _current_val = 0.0
                            for _leg in _legs:
                                _action = str(_leg.get("action", "")).upper()
                                _opt_type = str(_leg.get("option_type", "")).upper()
                                _strike = _leg.get("strike", 0)
                                _key = f"{_strike}{_opt_type}"
                                _ltp = _ltps.get(_key, 0)
                               
                                # Build display of LTP
                                if _current_ltp == "—":
                                    _current_ltp = f"₹{_ltp:.2f}"
                               
                                # P&L: if BUY, current_val = -LTP; if SELL, current_val = +LTP
                                if _action == "BUY":
                                    _current_val -= _ltp
                                else:  # SELL
                                    _current_val += _ltp
                           
                            # Unrealized P&L = current_value - entry_value (in INR)
                            _units_pos = int(_p.get("units_per_leg", 1) or 1)
                            _unrealized_inr = (_entry_premium - _current_val) * _units_pos
                            _unrealized_inr_num = float(_unrealized_inr)
                            _unrealized_pnl = f"₹{_unrealized_inr:,.0f}"
                            _valuation_source = "Broker LTP"
                except Exception as _e:
                    st.warning(f"LTP fetch error: {_e}")

                # Fallback: local option-chain valuation (works in dry-run/no-token mode).
                if _valuation_source == "—":
                    try:
                        if _oc_for_fallback is not None and _p.get("legs"):
                            from src.live_auto_runner import _position_value as _pos_val_fb
                            _cv_fb = _pos_val_fb(_p.get("legs") or [], _oc_for_fallback)
                            if _cv_fb is not None:
                                _units_pos = int(_p.get("units_per_leg", 1) or 1)
                                _unrealized_inr = (_entry_premium - float(_cv_fb)) * _units_pos
                                _unrealized_inr_num = float(_unrealized_inr)
                                _unrealized_pnl = f"₹{_unrealized_inr:,.0f}"
                                _current_ltp = f"Net ₹{float(_cv_fb):.2f}"
                                _valuation_source = "CSV Snapshot"
                    except Exception:
                        pass

                # Fallback: latest mark-to-market journal event for this position.
                if _valuation_source == "—":
                    _mtm = _latest_mtm.get(_pid)
                    if _mtm is not None:
                        try:
                            _unrealized_inr_num = float(_mtm.get("pnl_inr", 0) or 0)
                            _unrealized_pnl = f"₹{_unrealized_inr_num:,.0f}"
                            _cv_j = _mtm.get("current_value")
                            if _cv_j is not None:
                                _current_ltp = f"Net ₹{float(_cv_j):.2f}"
                            _valuation_source = "Journal MTM"
                        except Exception:
                            pass

                _total_unrealized_inr += _unrealized_inr_num
               
                _pos_rows.append({
                    "Position ID":   _pid,
                    "Broker":        _p.get("broker", "—"),
                    "Symbol":        _p.get("symbol", "—"),
                    "Strategy":      _p.get("strategy", "—"),
                    "Legs":          _fmt_legs(_p.get("legs")),
                    "Lots":          _p.get("lots", "—"),
                    "Expiry":        str(_p.get("expiry", "—")),
                    "Entry Premium": f"₹{_entry_premium:,.2f}",
                    "Current LTP":   _current_ltp,
                    "Unrealized P&L": _unrealized_pnl,
                    "Valuation":     _valuation_source,
                    "Est. Margin":   f"₹{_est_amt:,.0f}",
                    "Entry Time":    str(_p.get("entry_time", "—"))[:16],
                    "Status":        str(_p.get("status", "—")).upper(),
                    "Dry Run":       "🧪 Yes" if _p.get("dry_run") else "🔴 Live",
                    "Selection":     _p.get("selection_mode", "—"),
                    "Updated":       str(_p.get("updated_utc", "—"))[:16],
                })
            st.dataframe(pd.DataFrame(_pos_rows), hide_index=True, use_container_width=True)

            # ── Manual close buttons for each open position ──
            st.markdown("**Manual Close**")
            st.caption("Marks position as closed (paper exit). The running loop will also stop managing it.")
            for _pid, _p in _aopen.items():
                if str(_p.get("status", "")).lower() != "open":
                    continue
                _strat_label = _p.get("strategy", _pid)
                _legs_label  = _fmt_legs(_p.get("legs"))
                _col_lbl, _col_btn = st.columns([4, 1])
                with _col_lbl:
                    st.write(f"🔵 **{_strat_label}** — {_legs_label}")
                with _col_btn:
                    if st.button(f"✖ Close", key=f"manual_close_{_pid}",
                                 help=f"Manually close position {_pid}"):
                        try:
                            from src.live_broker_adapter import (
                                upsert_live_position, remove_live_position, append_journal_event
                            )
                            from datetime import datetime as _dt_mc, timezone as _tz_mc
                            _now_mc = _dt_mc.now()
                            upsert_live_position(_pid, {
                                "status": "closed",
                                "exit_trigger": "MANUAL_CLOSE",
                                "exit_time": _now_mc.isoformat(),
                            })
                            remove_live_position(_pid)
                            append_journal_event({
                                "event": "manual_close",
                                "position_id": _pid,
                                "symbol": _p.get("symbol", "NIFTY"),
                                "strategy": _p.get("strategy", ""),
                                "trigger": "MANUAL_CLOSE",
                                "entry_value": float(_p.get("entry_value", 0) or 0),
                                "dry_run": bool(_p.get("dry_run", True)),
                            })
                            st.success(f"✅ {_strat_label} position closed. Restart the loop to sync.")
                            st.rerun()
                        except Exception as _mc_exc:
                            st.error(f"Close failed: {_mc_exc}")
        else:
            st.info("No auto-algo positions tracked.")
    with _fa2:
        st.markdown("**Realized P&L today**")
        try:
            from src.live_auto_runner import _today_realized_pnl as _trp
            _realized = _trp()
        except Exception:
            _realized = 0.0
        _live_total = float(_realized) + float(_total_unrealized_inr)
        _m1, _m2, _m3 = st.columns(3)
        _m1.metric("Realized (auto exits)", f"₹{_realized:,.0f}")
        _m2.metric("Unrealized (open)", f"₹{_total_unrealized_inr:,.0f}")
        _m3.metric("Total (realized + unrealized)", f"₹{_live_total:,.0f}")
        st.caption("Realized updates only when a trade exits. Unrealized tracks open positions live during refresh.")

    st.markdown("**Execution journal (last 20)**")
    _ajrows = tail_journal(limit=20)
    if _ajrows:
        st.dataframe(pd.DataFrame(_ajrows), hide_index=True)
    else:
        st.info("No execution events yet.")

    st.markdown("**Trade P&L Timeline (entry → exit)**")
    _journal_path = Path("data/live_algo_journal.jsonl")
    if _journal_path.exists():
        _records = []
        for _line in _journal_path.read_text(encoding="utf-8").splitlines():
            try:
                _records.append(json.loads(_line))
            except Exception:
                continue

        _pos_ids = sorted({
            str(_r.get("position_id", "")).strip()
            for _r in _records
            if str(_r.get("position_id", "")).strip()
        })

        if _pos_ids:
            # Default to today's position (contains today's date string); fall back to last entry
            from datetime import datetime as _dt_tl
            _today_str = _dt_tl.now().strftime("%Y%m%d")
            _today_pids = [p for p in _pos_ids if _today_str in p]
            _default_pid_index = _pos_ids.index(_today_pids[-1]) if _today_pids else len(_pos_ids) - 1

            _selected_pid = st.selectbox(
                "Select position",
                _pos_ids,
                index=_default_pid_index,
                key="aat_pnl_timeline_pid")

            _events = [
                _r for _r in _records
                if str(_r.get("position_id", "")).strip() == _selected_pid
                and str(_r.get("event", "")) in {"auto_entry", "auto_mark_to_market", "auto_exit", "manual_close"}
            ]

            _timeline_rows = []
            for _ev in _events:
                _ts = pd.to_datetime(_ev.get("ts_utc"), errors="coerce")
                if pd.isna(_ts):
                    continue

                _event = str(_ev.get("event", ""))
                if _event == "auto_entry":
                    _pnl = 0.0
                else:
                    try:
                        _pnl = float(_ev.get("pnl_inr", 0) or 0)
                    except Exception:
                        _pnl = 0.0

                _timeline_rows.append({
                    "timestamp": _ts,
                    "pnl_inr": _pnl,
                    "event": _event,
                    "value_now": (
                        float(_ev.get("entry_value", 0) or 0) if _event == "auto_entry"
                        else float(_ev.get("current_value", 0) or 0) if _event == "auto_mark_to_market"
                        else float(_ev.get("exit_value", 0) or 0) if _event == "auto_exit"
                        else np.nan
                    ),
                })

            if _timeline_rows:
                _tdf = pd.DataFrame(_timeline_rows).sort_values("timestamp").reset_index(drop=True)
                # Convert UTC → IST (+5:30) so x-axis shows Indian market time
                if getattr(_tdf["timestamp"].dt, "tz", None) is not None:
                    _tdf["time"] = _tdf["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
                else:
                    _tdf["time"] = _tdf["timestamp"] + pd.Timedelta(hours=5, minutes=30)

                _entry_ts = _tdf.iloc[0]["time"]
                _tdf["mins_from_entry"] = (_tdf["time"] - _entry_ts).dt.total_seconds() / 60.0

                # Build a same-section session timeline so users can see that the
                # trade started mid-session rather than assuming morning data is missing.
                _session_open = _entry_ts.replace(hour=9, minute=15, second=0, microsecond=0)
                if _entry_ts < _session_open:
                    _session_open = _entry_ts
                _session_latest = _tdf["time"].max()

                # Determine tick format: HH:MM for intraday, dd-Mon HH:MM for multi-day
                _date_range_days = (_tdf["time"].max() - _tdf["time"].min()).days
                _xaxis_tickfmt = "%H:%M" if _date_range_days < 1 else "%d %b %H:%M"

                _fig_t = go.Figure()
                _fig_t.add_vrect(
                    x0=_session_open,
                    x1=_entry_ts,
                    fillcolor="rgba(160,160,160,0.18)",
                    line_width=0,
                    annotation_text="No trade before entry",
                    annotation_position="top left",
                )
                _fig_t.add_trace(go.Scatter(
                    x=_tdf["time"],
                    y=_tdf["pnl_inr"],
                    mode="lines+markers",
                    line={"color": "#1f77b4", "width": 2},
                    marker={"size": 6},
                    name="P&L",
                    customdata=np.stack([
                        _tdf["event"].astype(str),
                        _tdf["mins_from_entry"].round(1).astype(str)
                    ], axis=-1),
                    hovertemplate=(
                        "Time: %{x}<br>"
                        "P&L: ₹%{y:,.0f}<br>"
                        "Event: %{customdata[0]}<br>"
                        "Minutes from entry: %{customdata[1]}<extra></extra>"
                    )
                ))
                _fig_t.add_hline(y=0, line_width=1, line_color="#666")

                _exit_rows = _tdf[_tdf["event"].isin(["auto_exit", "manual_close"])]
                if not _exit_rows.empty:
                    _fig_t.add_vline(
                        x=_exit_rows.iloc[-1]["time"],
                        line_dash="dash",
                        line_color="#d62728",
                        annotation_text="Exit",
                        annotation_position="top left"
                    )

                _fig_t.update_layout(
                    title=f"P&L Timeline · {_selected_pid} (IST)",
                    xaxis_title="Time (IST)",
                    xaxis=dict(tickformat=_xaxis_tickfmt, tickangle=-30, range=[_session_open, _session_latest]),
                    yaxis_title="P&L (₹)",
                    margin={"l": 20, "r": 20, "t": 40, "b": 40},
                    height=360,
                )
                st.plotly_chart(_fig_t, use_container_width=True)

                st.caption(
                    f"Session shown from {_session_open.strftime('%H:%M')} IST. "
                    f"This trade actually entered at {_entry_ts.strftime('%H:%M')} IST, "
                    "so the shaded portion is pre-entry no-trade time, not missing market data."
                )

                if "day_move_pct" not in _events[0] and not any("day_move_pct" in _r for _r in _records):
                    pass
                else:
                    _market_rows = []
                    for _ev in _events:
                        _ts = pd.to_datetime(_ev.get("ts_utc"), errors="coerce")
                        if pd.isna(_ts):
                            continue
                        try:
                            _dm = float(_ev.get("day_move_pct", 0) or 0)
                        except Exception:
                            continue
                        _market_rows.append({"timestamp": _ts, "day_move_pct": _dm})

                    if _market_rows:
                        _mdf = pd.DataFrame(_market_rows).sort_values("timestamp").drop_duplicates(subset=["timestamp"])
                        if getattr(_mdf["timestamp"].dt, "tz", None) is not None:
                            _mdf["time"] = _mdf["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
                        else:
                            _mdf["time"] = _mdf["timestamp"] + pd.Timedelta(hours=5, minutes=30)

                        _fig_m = go.Figure()
                        _fig_m.add_vrect(
                            x0=_session_open,
                            x1=_entry_ts,
                            fillcolor="rgba(160,160,160,0.18)",
                            line_width=0,
                            annotation_text="No position yet",
                            annotation_position="top left",
                        )
                        _fig_m.add_trace(go.Scatter(
                            x=_mdf["time"],
                            y=_mdf["day_move_pct"],
                            mode="lines+markers",
                            line={"color": "#ff7f0e", "width": 2},
                            marker={"size": 5},
                            name="Day Move %",
                            hovertemplate="Time: %{x}<br>Day move: %{y:+.3f}%<extra></extra>",
                        ))
                        _fig_m.add_hline(y=0, line_width=1, line_color="#666")
                        _fig_m.update_layout(
                            title=f"Market Move During Trade Window · {_selected_pid} (IST)",
                            xaxis_title="Time (IST)",
                            xaxis=dict(tickformat=_xaxis_tickfmt, tickangle=-30, range=[_session_open, _session_latest]),
                            yaxis_title="Day Move %",
                            margin={"l": 20, "r": 20, "t": 40, "b": 40},
                            height=280,
                        )
                        st.plotly_chart(_fig_m, use_container_width=True)

                _last = _tdf.iloc[-1]
                _p1, _p2, _p3 = st.columns(3)
                _p1.metric("Current/Final P&L", f"₹{float(_last['pnl_inr']):,.0f}")
                _p2.metric("Max Profit Seen", f"₹{float(_tdf['pnl_inr'].max()):,.0f}")
                _p3.metric("Max Loss Seen", f"₹{float(_tdf['pnl_inr'].min()):,.0f}")

                _value_df = _tdf.dropna(subset=["value_now"]).copy()
                if len(_value_df) >= 2:
                    _fig_v = go.Figure()
                    _fig_v.add_trace(go.Scatter(
                        x=_value_df["time"],
                        y=_value_df["value_now"],
                        mode="lines+markers",
                        line={"color": "#2ca02c", "width": 2},
                        marker={"size": 6},
                        name="Net Premium Value",
                        hovertemplate=(
                            "Time: %{x}<br>"
                            "Net premium value: ₹%{y:,.2f}<extra></extra>"
                        )
                    ))
                    _fig_v.update_layout(
                        title=f"Premium Value Timeline · {_selected_pid} (IST)",
                        xaxis_title="Time (IST)",
                        xaxis=dict(tickformat=_xaxis_tickfmt, tickangle=-30),
                        yaxis_title="Net Premium Value (₹ per unit)",
                        margin={"l": 20, "r": 20, "t": 40, "b": 40},
                        height=300,
                    )
                    st.plotly_chart(_fig_v, use_container_width=True)
            else:
                st.info("No timeline data yet for this position. Run more ticks to accumulate P&L snapshots.")

            st.markdown("**Strategy Intratrade Analytics (run-up / drawdown)**")
            _by_pos = {}
            for _r in _records:
                _pid = str(_r.get("position_id", "")).strip()
                if not _pid:
                    continue
                if str(_r.get("event", "")) not in {"auto_entry", "auto_mark_to_market", "auto_exit", "manual_close"}:
                    continue
                _ts = pd.to_datetime(_r.get("ts_utc"), errors="coerce")
                if pd.isna(_ts):
                    continue
                _ev = str(_r.get("event", ""))
                if _ev == "auto_entry":
                    _pnl = 0.0
                else:
                    try:
                        _pnl = float(_r.get("pnl_inr", 0) or 0)
                    except Exception:
                        _pnl = 0.0
                _by_pos.setdefault(_pid, []).append({
                    "ts": _ts,
                    "pnl": _pnl,
                    "event": _ev,
                    "strategy": str(_r.get("strategy", "")).strip(),
                })

            _pos_metrics = []
            for _pid, _rows in _by_pos.items():
                _pdf = pd.DataFrame(_rows).sort_values("ts").reset_index(drop=True)
                if _pdf.empty:
                    continue
                _strategy = _pdf["strategy"].replace("", np.nan).dropna()
                _strategy_name = str(_strategy.iloc[0]) if not _strategy.empty else "Unknown"
                _closed = bool((_pdf["event"] == "auto_exit").any() or (_pdf["event"] == "manual_close").any())
                _start = _pdf.iloc[0]["ts"]
                _end = _pdf.iloc[-1]["ts"]
                _dur_min = (_end - _start).total_seconds() / 60.0
                _pos_metrics.append({
                    "position_id": _pid,
                    "strategy": _strategy_name,
                    "closed": _closed,
                    "final_pnl": float(_pdf.iloc[-1]["pnl"]),
                    "max_runup": float(_pdf["pnl"].max()),
                    "max_drawdown": float(_pdf["pnl"].min()),
                    "duration_min": round(_dur_min, 1),
                })

            if _pos_metrics:
                _pm_df = pd.DataFrame(_pos_metrics)
                _summary = _pm_df.groupby("strategy", dropna=False).agg(
                    Trades=("position_id", "count"),
                    Closed_Trades=("closed", "sum"),
                    Avg_Final_PnL=("final_pnl", "mean"),
                    Avg_Max_Runup=("max_runup", "mean"),
                    Avg_Max_Drawdown=("max_drawdown", "mean"),
                    Best_Runup=("max_runup", "max"),
                    Worst_Drawdown=("max_drawdown", "min"),
                ).reset_index()
                _summary = _summary.rename(columns={"strategy": "Strategy"})
                st.dataframe(_summary, hide_index=True, use_container_width=True)

                _fig_s = go.Figure()
                _fig_s.add_trace(go.Bar(
                    x=_summary["Strategy"],
                    y=_summary["Avg_Max_Runup"],
                    name="Avg Max Run-up",
                    marker_color="#1f77b4",
                ))
                _fig_s.add_trace(go.Bar(
                    x=_summary["Strategy"],
                    y=_summary["Avg_Max_Drawdown"],
                    name="Avg Max Drawdown",
                    marker_color="#d62728",
                ))
                _fig_s.update_layout(
                    barmode="group",
                    title="Strategy-wise Intratrade Excursions",
                    xaxis_title="Strategy",
                    yaxis_title="P&L (₹)",
                    height=320,
                    margin={"l": 20, "r": 20, "t": 40, "b": 20},
                )
                st.plotly_chart(_fig_s, use_container_width=True)
        else:
            st.info("No position IDs found in execution journal yet.")
    else:
        st.info("Execution journal file not found yet. It will be created after the first auto entry.")

    st.divider()

    # ── Section G · Strategy Selection & Backtest (dry-run) ──
    st.subheader("G · 🧠 Strategy Selection & Backtest (dry-run)")
    st.caption(
        "Evaluate the 4 paper-engine strategies live, filter by the **🧠 Smart (Win)** "
        "winner column, and review historical win-rates. Use this to decide which strategy "
        "`auto_winner` should pick. Everything here is read-only / dry-run — no orders are placed."
    )
    _g_sel = st.multiselect(
        "Strategies to evaluate",
        DEFAULT_STRATEGIES,
        default=list(aa_enabled_strats) if aa_enabled_strats else list(DEFAULT_STRATEGIES),
        format_func=lambda s: STRATEGY_LABELS.get(s, s),
        key="aat_g_strats")
    gcol1, gcol2 = st.columns(2)
    with gcol1:
        _do_eval = st.button("🔍 Evaluate strategies now (dry-run)", key="aat_eval")
    with gcol2:
        _do_bt = st.button("📊 Historical backtest / win-rate", key="aat_bt")

    if _do_eval:
        with st.spinner("Evaluating strategies on latest market data..."):
            _ev = evaluate_strategies(_g_sel or None)
        st.session_state["aat_eval_res"] = _ev
    _ev = st.session_state.get("aat_eval_res")
    if _ev:
        if not _ev.get("ok"):
            st.error(_ev.get("message", "Evaluation failed."))
        else:
            e1, e2, e3 = st.columns(3)
            e1.metric("Spot", f"{_ev.get('spot', 0):,.1f}")
            e2.metric("Sentiment", str(_ev.get("sentiment", "—")))
            e3.metric("VIX", f"{_ev.get('vix', 0):.2f}")
            _ideas = _ev.get("ideas", [])
            if _ideas:
                _idf = pd.DataFrame(_ideas)
                st.markdown("**All strategy ideas**")
                st.dataframe(_idf, hide_index=True)
                _smart = _idf[_idf.get("smart_win") == True] if "smart_win" in _idf.columns else _idf.iloc[0:0]
                st.markdown("**🧠 Smart (Win) candidates only**")
                if not _smart.empty:
                    st.dataframe(_smart, hide_index=True)
                else:
                    st.info("No Smart (Win) candidates in the current market snapshot.")
            else:
                st.info("No tradable ideas produced.")

    if _do_bt:
        with st.spinner("Reading auto_trade_log history..."):
            _btrows = backtest_winrate(_g_sel or None)
            _rec = recommend_strategy(_g_sel or None)
        st.session_state["aat_bt_rows"] = _btrows
        st.session_state["aat_rec"] = _rec
    _btrows = st.session_state.get("aat_bt_rows")
    if _btrows is not None:
        if _btrows:
            st.markdown("**Historical win-rate by strategy**")
            st.dataframe(pd.DataFrame(_btrows), hide_index=True)
        else:
            st.info("No closed trades found in auto_trade_log.json yet.")
        _rec = st.session_state.get("aat_rec")
        if _rec and _rec.get("ok") and _rec.get("recommended"):
            st.success(
                f"✅ Recommended (Smart-Win, best historical win-rate): "
                f"**{STRATEGY_LABELS.get(_rec['recommended'], _rec['recommended'])}** — {_rec.get('message', '')}"
            )
        elif _rec:
            st.info(_rec.get("message", "No confident recommendation yet."))
