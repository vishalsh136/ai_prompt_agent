"""
src/utils.py — Common helpers for the Indian Market Study Tool
==============================================================

What this module provides
--------------------------
1. Logging setup           – writes events to both console and log file.
2. Config loader           – reads config.yaml.
3. Black-Scholes model     – theoretical option pricing (European options).
4. Greeks calculator       – Delta, Gamma, Theta, Vega.
5. Formatting helpers      – Indian rupee formatting, percentage display.

Why these matter
----------------
Black-Scholes (1973) is the foundation of modern options pricing. Even though
real NSE options use a slightly modified model (and are American-style for
stocks), Black-Scholes gives excellent approximations for index options and
is the first thing every options student should understand.

⚠️  DISCLAIMER: All calculations here are for EDUCATIONAL PURPOSES ONLY.
    Do NOT use them as trading signals or financial advice.
"""

import logging
import os
from pathlib import Path

import numpy as np
import yaml
from scipy.stats import norm


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_file: str = "logs/app.log", level: str = "INFO") -> logging.Logger:
    """
    Configure application-wide logging.

    Log entries are written to both the console and a rotating file so you
    can review backtest runs, parameter changes, and errors later.

    Parameters
    ----------
    log_file : str
        Path to the log file (created automatically).
    level : str
        Logging level — "DEBUG", "INFO", "WARNING", "ERROR".

    Returns
    -------
    logging.Logger
        The root logger for the application.
    """
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Avoid adding duplicate handlers on repeated calls (e.g., Streamlit reruns)
    root = logging.getLogger("market_study_tool")
    if not root.handlers:
        root.setLevel(log_level)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # File handler
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    return root


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def get_config(config_path: str = "config.yaml") -> dict:
    """
    Load the YAML configuration file.

    Parameters
    ----------
    config_path : str
        Path to config.yaml (relative to project root).

    Returns
    -------
    dict
        Parsed configuration dictionary.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path.resolve()}\n"
            "Make sure you run the app from the project root directory."
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Black-Scholes Option Pricing Model
# ---------------------------------------------------------------------------

def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "CE",
) -> float:
    """
    Calculate theoretical option price using the Black-Scholes model.

    The Black-Scholes model assumes:
    ✓ The underlying follows Geometric Brownian Motion (log-normal returns).
    ✓ No dividends paid during the option's life.
    ✓ Constant risk-free rate and volatility throughout.
    ✓ European-style exercise (only at expiry).
    ✓ No transaction costs or taxes.

    Formula:
        d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)
        d2 = d1 − σ·√T
        Call price  = S·N(d1) − K·e^(−rT)·N(d2)
        Put price   = K·e^(−rT)·N(−d2) − S·N(−d1)
    where N(·) is the cumulative standard normal distribution.

    Parameters
    ----------
    S : float
        Current spot (or futures) price of the underlying.
    K : float
        Strike price of the option.
    T : float
        Time to expiry in YEARS.
        Example: 30 days → T = 30/365 ≈ 0.082
    r : float
        Annualised risk-free interest rate as a decimal.
        Example: 7% p.a. → r = 0.07
    sigma : float
        Implied volatility as a decimal (annualised).
        Example: 18% → sigma = 0.18
    option_type : str
        'CE' for Call (buyer profits when S > K at expiry).
        'PE' for Put  (buyer profits when S < K at expiry).

    Returns
    -------
    float
        Theoretical option premium (≥ 0).

    Notes
    -----
    For Indian index options on NSE, the model gives a good approximation
    but real prices may differ due to dividends, early exercise (for stocks),
    and market microstructure effects.
    """
    # Validate inputs
    if T <= 0:
        # At or past expiry: value is pure intrinsic value
        if option_type == "CE":
            return float(max(S - K, 0.0))
        else:
            return float(max(K - S, 0.0))

    if sigma <= 0 or S <= 0 or K <= 0:
        return 0.0

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "CE":
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:  # PE
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return float(max(price, 0.0))


# ---------------------------------------------------------------------------
# Option Greeks
# ---------------------------------------------------------------------------

def compute_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "CE",
) -> dict:
    """
    Calculate the four main option Greeks using Black-Scholes.

    Greeks tell you how an option's price changes when one input changes
    while all others stay constant (ceteris paribus). They are essential
    for understanding risk and for position management.

    DELTA (δ)
    ---------
    Rate of change of option price with respect to the underlying price.
    • Call Delta: between 0 and 1  → ATM call ≈ 0.50
    • Put Delta : between −1 and 0 → ATM put  ≈ −0.50
    Intuition: A delta of 0.60 means the option moves ₹0.60 for every ₹1
    move in the underlying.

    GAMMA (Γ)
    ---------
    Rate of change of Delta with respect to the underlying price.
    High gamma (near-ATM, near-expiry) means delta changes rapidly — the
    option can quickly become deeply ITM or worthless. Gamma risk is highest
    on expiry day.

    THETA (Θ)
    ---------
    Daily time decay — how much value the option loses per calendar day,
    all else equal. Theta is typically negative for buyers (you lose money
    as time passes) and positive for sellers (you gain from time decay).
    This is why selling options is called 'theta harvesting'.

    VEGA (ν)
    --------
    Sensitivity to a 1% change in implied volatility.
    Long options have positive vega (benefit from rising IV).
    Short options have negative vega (hurt by rising IV).

    Parameters
    ----------
    S, K, T, r, sigma, option_type : same as black_scholes_price()

    Returns
    -------
    dict with keys: delta, gamma, theta, vega
    """
    if T <= 0 or sigma <= 0:
        itm = (option_type == "CE" and S > K) or (option_type == "PE" and S < K)
        return {"delta": 1.0 if itm else 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    # Delta
    if option_type == "CE":
        delta = float(norm.cdf(d1))
    else:
        delta = float(norm.cdf(d1) - 1.0)

    # Gamma (identical for calls and puts by put-call parity)
    gamma = float(norm.pdf(d1) / (S * sigma * np.sqrt(T)))

    # Theta (daily; divide annual formula by 365)
    theta_base = -(S * norm.pdf(d1) * sigma) / (2.0 * np.sqrt(T))
    if option_type == "CE":
        theta = float((theta_base - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365.0)
    else:
        theta = float((theta_base + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365.0)

    # Vega: value change for a +1% (0.01) change in volatility
    vega = float(S * norm.pdf(d1) * np.sqrt(T) * 0.01)

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 2),
        "vega":  round(vega,  2),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_inr(value: float) -> str:
    """
    Format a float as Indian Rupees with compact suffixes.

    Examples
    --------
    >>> format_inr(25000000)   # '₹2.50 Cr'
    >>> format_inr(150000)     # '₹1.50 L'
    >>> format_inr(4500.75)    # '₹4,500.75'
    """
    if abs(value) >= 1e7:
        return f"₹{value / 1e7:.2f} Cr"
    elif abs(value) >= 1e5:
        return f"₹{value / 1e5:.2f} L"
    else:
        return f"₹{value:,.2f}"


def pct_str(value: float, decimals: int = 2) -> str:
    """Format a decimal fraction as a percentage string, e.g. 0.154 → '+15.40%'."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.{decimals}f}%"


def color_for_value(value: float, good_positive: bool = True) -> str:
    """Return 'green' or 'red' depending on value sign and convention."""
    if good_positive:
        return "green" if value >= 0 else "red"
    return "red" if value >= 0 else "green"
