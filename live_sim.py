"""
RealWinner EA v5 — Live Simulator

Simula il bot in real-time: prezzi sintetici tick-by-tick, trading automatico,
P&L in tempo reale, storico trade, log eventi.

Avvio:
    streamlit run live_sim.py
"""

import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RealWinner EA — Live Simulator",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .big-price { font-size: 2.4em; font-weight: 900; letter-spacing: 1px; font-family: monospace; }
    .price-up   { color: #22c55e; }
    .price-down { color: #ef4444; }
    .trade-card { border-radius: 10px; padding: 14px; margin-bottom: 8px; }
    .trade-long  { background: #0d1f12; border-left: 4px solid #22c55e; }
    .trade-short { background: #1f0d0d; border-left: 4px solid #ef4444; }
    div[data-testid="stMetricValue"] { font-size: 1.25em; }
    .log-entry { font-size: 0.82em; border-bottom: 1px solid #1e293b; padding: 3px 0; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
START_BALANCE   = 10_000.0
SYMBOL          = "EURUSD"
SPREAD          = 0.00012       # 1.2 pip
POINT           = 0.00001
PIP_VALUE       = 10.0          # EUR per pip per standard lot (EURUSD)

RISK_PCT        = 0.009         # 0.9% per trade
ATR_SL_MULT     = 1.1
TP1_RR          = 1.5
TP2_RR          = 3.0
CONFLUENCE_MIN  = 2
MAX_DAILY_LOSS  = 0.024
DAILY_WARNING   = 0.007
MAX_CONSEC_LOSS = 3

TICKS_PER_CANDLE = 60           # tick → M1 candle
SIM_TICK_RATE    = 3            # tick per rerun (velocità base)

# ─────────────────────────────────────────────────────────────────────────────
# PRICE SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def next_tick(price: float, regime: str, rng: np.random.Generator) -> float:
    vol = 0.000022
    if regime == "trend_up":
        drift = 0.0000035
    elif regime == "trend_down":
        drift = -0.0000035
    else:
        drift = (1.0800 - price) * 0.0004   # mean-reversion verso 1.0800
    return round(price + drift + rng.normal(0, vol), 5)


def ticks_to_bar(ticks: list, t: datetime) -> dict:
    arr = np.array(ticks)
    return {
        "time":   t,
        "open":   ticks[0],
        "high":   float(arr.max()),
        "low":    float(arr.min()),
        "close":  ticks[-1],
        "volume": len(ticks),
    }


# ─────────────────────────────────────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────────────────────────────────────

def _ema(s, period):
    return s.ewm(span=period, adjust=False).mean()

def _rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    l = (-d).clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def _bollinger(s, period=20, dev=2.0):
    mid = s.rolling(period).mean()
    std = s.rolling(period).std()
    return mid + dev*std, mid, mid - dev*std

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    df["ema9"]   = _ema(c, 9)
    df["ema21"]  = _ema(c, 21)
    df["ema50"]  = _ema(c, 50)
    df["ema200"] = _ema(c, 200)
    df["rsi"]    = _rsi(c, 14)
    df["atr"]    = _atr(df, 14)
    df["bb_up"], df["bb_mid"], df["bb_lo"] = _bollinger(c, 20, 2.0)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def get_signals(df: pd.DataFrame) -> dict:
    empty = {"signal": 0, "trend": 0, "mr": 0, "htf": 0, "bull": 0, "bear": 0, "atr": 0.0008}
    if len(df) < 210:
        return empty
    r = df.iloc[-2]

    # HTF bias — usa ultimi 96 bar come proxy H4
    htf_close = df["close"].iloc[-96:]
    e_fast_h4  = htf_close.ewm(span=9,  adjust=False).mean().iloc[-1]
    e_slow_h4  = htf_close.ewm(span=48, adjust=False).mean().iloc[-1]
    htf = 1 if e_fast_h4 > e_slow_h4 else -1

    # Trend
    trend = 0
    if r["ema9"] > r["ema21"] > r["ema50"] and r["close"] > r["ema200"] and 50 <= r["rsi"] <= 78:
        trend = 1
    elif r["ema9"] < r["ema21"] < r["ema50"] and r["close"] < r["ema200"] and 22 <= r["rsi"] <= 50:
        trend = -1

    # Mean Reversion (solo ranging)
    mr = 0
    if abs(r["ema9"] - r["ema50"]) < 0.0020:
        if r["close"] <= r["bb_lo"] and r["rsi"] <= 30:
            mr = 1
        elif r["close"] >= r["bb_up"] and r["rsi"] >= 70:
            mr = -1

    # HTF segnale (allineamento con trend)
    htf_sig = 1 if (htf == 1 and trend == 1) else (-1 if (htf == -1 and trend == -1) else 0)

    bull = int(trend == 1) + int(mr == 1) + int(htf_sig == 1)
    bear = int(trend == -1) + int(mr == -1) + int(htf_sig == -1)
    signal = 1 if bull >= CONFLUENCE_MIN else (-1 if bear >= CONFLUENCE_MIN else 0)

    return {
        "signal": signal,
        "trend":  trend,
        "mr":     mr,
        "htf":    htf_sig,
        "bull":   bull,
        "bear":   bear,
        "atr":    float(r["atr"]) if not np.isnan(r["atr"]) else 0.0008,
    }


# ─────────────────────────────────────────────────────────────────────────────
# TRADE MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def _lot_size(balance: float, sl_pips: float) -> float:
    risk_eur = balance * RISK_PCT
    lot = risk_eur / (sl_pips * PIP_VALUE)
    return round(max(0.01, min(lot, 5.0)), 2)


def create_trade(direction: int, price: float, atr: float, balance: float, t: datetime) -> dict:
    sl_dist = max(atr * ATR_SL_MULT, 0.0010)
    sl_pips = sl_dist / POINT / 10
    lot = _lot_size(balance, sl_pips)

    if direction == 1:
        entry = round(price + SPREAD, 5)
        sl    = round(entry - sl_dist, 5)
        tp1   = round(entry + sl_dist * TP1_RR, 5)
        tp2   = round(entry + sl_dist * TP2_RR, 5)
    else:
        entry = round(price, 5)
        sl    = round(entry + sl_dist, 5)
        tp1   = round(entry - sl_dist * TP1_RR, 5)
        tp2   = round(entry - sl_dist * TP2_RR, 5)

    return {
        "direction":    direction,
        "entry":        entry,
        "sl":           sl,
        "tp1":          tp1,
        "tp2":          tp2,
        "sl_dist":      sl_dist,
        "lot":          lot,
        "lot_remaining": lot,
        "tp1_hit":      False,
        "open_time":    t,
        "status":       "open",
        "pnl":          0.0,
        "pips":         0.0,
        "current_price": entry,
    }


def update_trade(trade: dict, price: float, t: datetime) -> tuple:
    """Ritorna (trade_aggiornato, lista_eventi_chiusura_parziale)."""
    events = []
    d   = trade["direction"]
    bid = price
    ask = round(price + SPREAD, 5)
    cur = ask if d == 1 else bid

    dist      = (cur - trade["entry"]) * d
    pips      = dist / POINT / 10
    trade["pnl"]           = round(pips * PIP_VALUE * trade["lot_remaining"], 2)
    trade["pips"]          = round(pips, 1)
    trade["current_price"] = cur

    # TP1
    if not trade["tp1_hit"]:
        hit = (d == 1 and bid >= trade["tp1"]) or (d == -1 and ask <= trade["tp1"])
        if hit:
            closed_lot = round(trade["lot"] * 0.5, 2)
            tp1_pips   = abs(trade["tp1"] - trade["entry"]) / POINT / 10
            tp1_pnl    = round(tp1_pips * PIP_VALUE * closed_lot, 2)
            events.append({"time": t.strftime("%H:%M:%S"), "type": "TP1",
                           "direction": "LONG" if d == 1 else "SHORT",
                           "entry": trade["entry"], "exit": trade["tp1"],
                           "lot": closed_lot, "pnl": tp1_pnl, "pips": round(tp1_pips, 1)})
            trade["tp1_hit"]      = True
            trade["lot_remaining"] = round(trade["lot"] * 0.5, 2)
            # Break-even sul residuo
            buf = 0.00008
            trade["sl"] = trade["entry"] + buf if d == 1 else trade["entry"] - buf

    # TP2
    if trade["tp1_hit"]:
        hit2 = (d == 1 and bid >= trade["tp2"]) or (d == -1 and ask <= trade["tp2"])
        if hit2:
            tp2_pips = abs(trade["tp2"] - trade["entry"]) / POINT / 10
            tp2_pnl  = round(tp2_pips * PIP_VALUE * trade["lot_remaining"], 2)
            events.append({"time": t.strftime("%H:%M:%S"), "type": "TP2",
                           "direction": "LONG" if d == 1 else "SHORT",
                           "entry": trade["entry"], "exit": trade["tp2"],
                           "lot": trade["lot_remaining"], "pnl": tp2_pnl, "pips": round(tp2_pips, 1)})
            trade["status"]        = "closed"
            trade["lot_remaining"] = 0
            trade["pnl"]          = 0.0
            return trade, events

    # SL
    sl_hit = (d == 1 and bid <= trade["sl"]) or (d == -1 and ask >= trade["sl"])
    if sl_hit:
        sl_pips = abs(trade["sl"] - trade["entry"]) / POINT / 10
        sl_sign = 1.0 if trade["tp1_hit"] else -1.0      # dopo TP1 può essere BE o profit
        sl_pnl  = round(sl_sign * sl_pips * PIP_VALUE * trade["lot_remaining"], 2)
        events.append({"time": t.strftime("%H:%M:%S"),
                       "type": "SL" if not trade["tp1_hit"] else "SL(BE)",
                       "direction": "LONG" if d == 1 else "SHORT",
                       "entry": trade["entry"], "exit": trade["sl"],
                       "lot": trade["lot_remaining"], "pnl": sl_pnl,
                       "pips": round(sl_sign * sl_pips, 1)})
        trade["status"]        = "closed"
        trade["lot_remaining"] = 0
        trade["pnl"]          = 0.0

    return trade, events


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE — INIT
# ─────────────────────────────────────────────────────────────────────────────

def init_sim():
    if "sim_ready" in st.session_state:
        return

    rng   = np.random.default_rng(int(time.time()) % 100000)
    price = 1.0800
    regime        = "ranging"
    regime_left   = 60
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    # Genera 260 barre M1 storiche
    bars   = []
    buffer = []
    tc     = 0
    bar_t  = now - timedelta(minutes=260)

    for _ in range(260 * TICKS_PER_CANDLE):
        price = next_tick(price, regime, rng)
        buffer.append(price)
        tc += 1
        regime_left -= 1
        if regime_left <= 0:
            regime = rng.choice(["trend_up", "trend_down", "ranging"], p=[0.35, 0.35, 0.30])
            regime_left = int(rng.integers(40, 120))
        if tc >= TICKS_PER_CANDLE:
            bars.append(ticks_to_bar(buffer[:TICKS_PER_CANDLE], bar_t))
            buffer = buffer[TICKS_PER_CANDLE:]
            tc     = 0
            bar_t  += timedelta(minutes=1)

    st.session_state.update({
        "sim_ready":        True,
        "sim_rng":          rng,
        "sim_bars":         bars,
        "sim_price":        price,
        "sim_tick_buf":     list(buffer),
        "sim_tick_count":   tc,
        "sim_regime":       regime,
        "sim_regime_left":  regime_left,
        "sim_candle_time":  bar_t,
        "sim_balance":      START_BALANCE,
        "sim_open_trade":   None,
        "sim_trade_history": [],
        "sim_event_log":    [],
        "sim_running":      True,
        "sim_start_balance": START_BALANCE,
        "sim_daily_start":  START_BALANCE,
        "sim_consec_loss":  0,
        "sim_last_sig":     0,
        "sim_speed":        1,
    })


# ─────────────────────────────────────────────────────────────────────────────
# ADVANCE SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def advance_sim(ticks_to_generate: int = SIM_TICK_RATE):
    ss   = st.session_state
    rng  = ss.sim_rng
    price       = ss.sim_price
    regime      = ss.sim_regime
    regime_left = ss.sim_regime_left
    now         = datetime.now(timezone.utc)

    for _ in range(ticks_to_generate):
        price = next_tick(price, regime, rng)
        ss.sim_tick_buf.append(price)
        ss.sim_tick_count += 1
        regime_left -= 1
        if regime_left <= 0:
            regime = rng.choice(["trend_up", "trend_down", "ranging"], p=[0.35, 0.35, 0.30])
            regime_left = int(rng.integers(40, 120))

    ss.sim_price        = price
    ss.sim_regime       = regime
    ss.sim_regime_left  = regime_left

    # Chiudi candle M1 se tick sufficienti
    new_bar_closed = False
    while ss.sim_tick_count >= TICKS_PER_CANDLE:
        bar_ticks = ss.sim_tick_buf[:TICKS_PER_CANDLE]
        ss.sim_tick_buf   = ss.sim_tick_buf[TICKS_PER_CANDLE:]
        ss.sim_tick_count -= TICKS_PER_CANDLE
        ss.sim_candle_time += timedelta(minutes=1)
        ss.sim_bars.append(ticks_to_bar(bar_ticks, ss.sim_candle_time))
        if len(ss.sim_bars) > 350:
            ss.sim_bars = ss.sim_bars[-350:]
        new_bar_closed = True

    balance    = ss.sim_balance
    open_trade = ss.sim_open_trade

    # Aggiorna trade aperto
    if open_trade is not None and open_trade["status"] == "open":
        open_trade, events = update_trade(open_trade, price, now)
        for ev in events:
            balance += ev["pnl"]
            ss.sim_trade_history.insert(0, ev)
            ev_log = {**ev, "balance_after": round(balance, 2)}
            ss.sim_event_log.insert(0, ev_log)
            if ev["type"] == "SL":
                ss.sim_consec_loss += 1
            else:
                ss.sim_consec_loss = 0

        if open_trade["status"] == "closed":
            ss.sim_open_trade = None
        else:
            ss.sim_open_trade = open_trade
        ss.sim_balance = round(balance, 2)

    # Controlla segnali su nuova barra (se nessun trade aperto)
    if new_bar_closed and ss.sim_open_trade is None and len(ss.sim_bars) >= 210:
        df = pd.DataFrame(ss.sim_bars)
        df = compute_indicators(df)
        sig = get_signals(df)

        daily_dd = (ss.sim_daily_start - balance) / ss.sim_daily_start
        too_many_losses = ss.sim_consec_loss >= MAX_CONSEC_LOSS

        if sig["signal"] != 0 and daily_dd < MAX_DAILY_LOSS and not too_many_losses:
            atr_val = sig["atr"] if sig["atr"] > 0 else 0.0008
            # Riduzione lot se in warning
            effective_balance = balance * 0.5 if daily_dd >= DAILY_WARNING else balance
            trade = create_trade(sig["signal"], price, atr_val, effective_balance, now)
            ss.sim_open_trade = trade
            dir_label = "LONG" if sig["signal"] == 1 else "SHORT"
            ss.sim_event_log.insert(0, {
                "time":          now.strftime("%H:%M:%S"),
                "type":          f"OPEN {dir_label}",
                "direction":     dir_label,
                "pnl":           0,
                "pips":          0,
                "lot":           trade["lot"],
                "entry":         trade["entry"],
                "sl":            trade["sl"],
                "balance_after": round(balance, 2),
            })

    # Trim log
    ss.sim_event_log     = ss.sim_event_log[:200]
    ss.sim_trade_history = ss.sim_trade_history[:500]


# ─────────────────────────────────────────────────────────────────────────────
# CHART
# ─────────────────────────────────────────────────────────────────────────────

def build_chart(bars: list, open_trade: dict | None, n: int = 80) -> go.Figure:
    df = pd.DataFrame(bars).tail(n + 50)
    df = compute_indicators(df)
    df = df.tail(n).reset_index(drop=True)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.03,
        subplot_titles=("EURUSD M1 — LIVE SIM", "RSI"),
    )

    # Candele
    fig.add_trace(go.Candlestick(
        x=df["time"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color="#22c55e", decreasing_line_color="#ef4444",
        name="Price", showlegend=False,
    ), row=1, col=1)

    # EMAs
    for col, color, lbl in [
        ("ema9",   "#60a5fa", "EMA9"),
        ("ema21",  "#a78bfa", "EMA21"),
        ("ema50",  "#f59e0b", "EMA50"),
        ("ema200", "#f43f5e", "EMA200"),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["time"], y=df[col],
                line=dict(color=color, width=1),
                name=lbl,
            ), row=1, col=1)

    # Bollinger
    if "bb_up" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["bb_up"],
            line=dict(color="rgba(148,163,184,0.3)", width=1, dash="dot"),
            showlegend=False, name="BB",
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["bb_lo"],
            line=dict(color="rgba(148,163,184,0.3)", width=1, dash="dot"),
            fill="tonexty", fillcolor="rgba(148,163,184,0.04)",
            showlegend=False,
        ), row=1, col=1)

    # Livelli trade aperto
    if open_trade and open_trade["status"] == "open":
        d      = open_trade["direction"]
        c_main = "#22c55e" if d == 1 else "#ef4444"
        x0, x1 = df["time"].iloc[0], df["time"].iloc[-1]
        levels = [
            (open_trade["entry"], "Entry", c_main,   "solid"),
            (open_trade["sl"],    "SL",    "#ef4444", "dash"),
            (open_trade["tp1"],   "TP1",   "#86efac", "dot"),
            (open_trade["tp2"],   "TP2",   "#22c55e", "dot"),
        ]
        for lvl, lbl, col, dash in levels:
            fig.add_shape(type="line", x0=x0, x1=x1, y0=lvl, y1=lvl,
                          line=dict(color=col, width=1.5, dash=dash), row=1, col=1)
            fig.add_annotation(x=x1, y=lvl, text=f" {lbl} {lvl:.5f}",
                               showarrow=False, xanchor="left",
                               font=dict(color=col, size=10), row=1, col=1)

    # Prezzo corrente (linea tratteggiata bianca)
    cur_price = df["close"].iloc[-1]
    fig.add_shape(type="line",
                  x0=df["time"].iloc[0], x1=df["time"].iloc[-1],
                  y0=cur_price, y1=cur_price,
                  line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dot"),
                  row=1, col=1)

    # RSI
    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["rsi"],
            line=dict(color="#a78bfa", width=1.5),
            name="RSI", showlegend=False,
        ), row=2, col=1)
        for lvl, col in [(70, "rgba(239,68,68,0.35)"), (30, "rgba(34,197,94,0.35)"),
                         (50, "rgba(148,163,184,0.2)")]:
            fig.add_hline(y=lvl, line=dict(color=col, width=1, dash="dash"), row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=520,
        margin=dict(l=0, r=100, t=30, b=0),
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=10)),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────────────────────────────────────

def render():
    ss = st.session_state

    # ── Sidebar
    st.sidebar.title("🤖 Live Simulator")
    ss.sim_running = st.sidebar.toggle("▶️ Simulazione attiva", value=ss.sim_running)
    speed = st.sidebar.select_slider("Velocità", options=[1, 2, 5, 10, 20], value=ss.sim_speed)
    ss.sim_speed = speed

    if st.sidebar.button("🔄 Reset simulazione"):
        for k in [k for k in ss.keys() if k.startswith("sim_")]:
            del ss[k]
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Parametri EA**")
    st.sidebar.caption(f"Risk: {RISK_PCT*100:.1f}% | TP1 {TP1_RR}R | TP2 {TP2_RR}R")
    st.sidebar.caption(f"Confluenza min: {CONFLUENCE_MIN} | Max daily DD: {MAX_DAILY_LOSS*100:.1f}%")
    st.sidebar.caption(f"Spread: {SPREAD/POINT/10:.1f} pip")

    # ── Dati correnti
    price      = ss.sim_price
    bars       = ss.sim_bars
    open_trade = ss.sim_open_trade
    balance    = ss.sim_balance
    start_bal  = ss.sim_start_balance
    history    = ss.sim_trade_history
    event_log  = ss.sim_event_log

    open_pnl   = open_trade["pnl"] if open_trade else 0.0
    equity     = balance + open_pnl
    total_pnl  = equity - start_bal
    total_dd   = max(0.0, (start_bal - equity) / start_bal * 100)
    daily_dd   = max(0.0, (ss.sim_daily_start - equity) / ss.sim_daily_start * 100)

    prev_price  = bars[-2]["close"] if len(bars) >= 2 else price
    price_diff  = price - prev_price
    arrow       = "▲" if price_diff >= 0 else "▼"
    price_class = "price-up" if price_diff >= 0 else "price-down"

    regime_icons = {"trend_up": "📈 Trending Up", "trend_down": "📉 Trending Down", "ranging": "↔️ Ranging"}
    regime_label = regime_icons.get(ss.sim_regime, ss.sim_regime)

    # ── HEADER — prezzo live
    st.title("🤖 RealWinner EA — Live Simulator")

    hdr1, hdr2, hdr3, hdr4 = st.columns([3, 2, 2, 2])
    with hdr1:
        st.markdown(
            f'<div class="big-price"><span class="{price_class}">'
            f'{SYMBOL} &nbsp; {price:.5f} &nbsp; {arrow} {price_diff:+.5f}'
            f'</span></div>',
            unsafe_allow_html=True,
        )
    hdr2.metric("Regime mercato", regime_label)
    hdr3.metric("Barre M1", len(bars))
    status_icon = "🟢 RUNNING" if ss.sim_running else "⏸️ PAUSED"
    hdr4.metric("Stato", status_icon)

    st.markdown("---")

    # ── Account metrics
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Balance",      f"{balance:,.2f} €")
    m2.metric("Equity",       f"{equity:,.2f} €",  delta=f"{total_pnl:+.2f}")
    m3.metric("P&L Open",     f"{open_pnl:+.2f} €",  delta_color="normal" if open_pnl >= 0 else "inverse")
    m4.metric("Total P&L",    f"{total_pnl:+.2f} €",  delta_color="normal" if total_pnl >= 0 else "inverse")
    m5.metric("Daily DD",     f"{daily_dd:.2f}%",    delta_color="inverse" if daily_dd > 0 else "off")
    m6.metric("Max DD",       f"{total_dd:.2f}%",    delta_color="inverse" if total_dd > 0 else "off")

    # Alert banner
    if daily_dd >= MAX_DAILY_LOSS * 100:
        st.error(f"🛑 **MAX DAILY LOSS RAGGIUNTO** ({daily_dd:.2f}%) — EA in attesa domani")
    elif daily_dd >= DAILY_WARNING * 100:
        st.warning(f"⚠️ **Daily Warning** ({daily_dd:.2f}%) — Lot size dimezzato")
    if ss.sim_consec_loss >= MAX_CONSEC_LOSS:
        st.warning(f"⚠️ **{ss.sim_consec_loss} perdite consecutive** — EA in pausa cautela")

    st.markdown("---")

    # ── Chart + Trade panel
    chart_col, side_col = st.columns([3, 1])

    with chart_col:
        st.plotly_chart(build_chart(bars, open_trade, n=80), use_container_width=True)

    with side_col:
        # Trade aperto
        st.markdown("#### Posizione")
        if open_trade and open_trade["status"] == "open":
            d         = open_trade["direction"]
            dir_label = "▲ LONG" if d == 1 else "▼ SHORT"
            css       = "trade-long" if d == 1 else "trade-short"
            pnl_color = "#22c55e" if open_trade["pnl"] >= 0 else "#ef4444"
            tp1_str   = "✅ HIT" if open_trade["tp1_hit"] else f"{open_trade['tp1']:.5f}"
            lot_rem   = open_trade["lot_remaining"]
            lot_orig  = open_trade["lot"]

            st.markdown(f"""
<div class="trade-card {css}">
  <div style="font-size:1.5em;font-weight:900">{dir_label}</div>
  <div style="margin:6px 0;color:#94a3b8;font-size:0.85em">
    Lot: <b style="color:#e2e8f0">{lot_rem:.2f}</b>
    {f"/ {lot_orig:.2f}" if lot_rem != lot_orig else ""}
  </div>
  <hr style="border-color:#334155;margin:8px 0">
  <div>Entry &nbsp;<code>{open_trade['entry']:.5f}</code></div>
  <div>Now &nbsp;&nbsp;<code>{open_trade.get('current_price', price):.5f}</code></div>
  <div>Pips &nbsp;&nbsp;<b>{open_trade.get('pips', 0.0):+.1f}</b></div>
  <div style="font-size:1.35em;font-weight:800;color:{pnl_color};margin-top:6px">
    {open_trade['pnl']:+.2f} €
  </div>
  <hr style="border-color:#334155;margin:8px 0">
  <div>SL &nbsp; <code style="color:#ef4444">{open_trade['sl']:.5f}</code></div>
  <div>TP1 &nbsp;<code style="color:#86efac">{tp1_str}</code></div>
  <div>TP2 &nbsp;<code style="color:#22c55e">{open_trade['tp2']:.5f}</code></div>
</div>
""", unsafe_allow_html=True)
        else:
            st.markdown("""
<div class="trade-card" style="background:#111827;border-left:4px solid #334155;border-radius:10px;padding:14px">
  <div style="color:#94a3b8;font-size:1.1em">⏳ Nessuna posizione</div>
  <div style="color:#64748b;font-size:0.85em;margin-top:6px">In attesa di segnale confluente...</div>
</div>
""", unsafe_allow_html=True)

        # Event log
        st.markdown("#### Log eventi")
        for ev in event_log[:18]:
            etype = ev.get("type", "")
            if "OPEN" in etype:
                icon = "🟢" if "LONG" in etype else "🔴"
                lot  = ev.get("lot", 0)
                ent  = ev.get("entry", 0)
                sl   = ev.get("sl", 0)
                st.markdown(
                    f'<div class="log-entry">{icon} <b>{ev["time"]}</b> {etype}<br>'
                    f'<span style="color:#94a3b8">lot {lot:.2f} | entry {ent:.5f} | sl {sl:.5f}</span></div>',
                    unsafe_allow_html=True,
                )
            elif etype == "TP1":
                st.markdown(
                    f'<div class="log-entry">✅ <b>{ev["time"]}</b> TP1 {ev.get("direction","")}'
                    f' <span style="color:#22c55e">+{ev["pnl"]:.2f}€ (+{ev["pips"]:.1f}p)</span></div>',
                    unsafe_allow_html=True,
                )
            elif etype == "TP2":
                st.markdown(
                    f'<div class="log-entry">🏆 <b>{ev["time"]}</b> TP2 {ev.get("direction","")}'
                    f' <span style="color:#22c55e">+{ev["pnl"]:.2f}€ (+{ev["pips"]:.1f}p)</span></div>',
                    unsafe_allow_html=True,
                )
            elif "SL" in etype:
                color = "#86efac" if ev["pnl"] >= 0 else "#ef4444"
                st.markdown(
                    f'<div class="log-entry">❌ <b>{ev["time"]}</b> {etype} {ev.get("direction","")}'
                    f' <span style="color:{color}">{ev["pnl"]:+.2f}€ ({ev["pips"]:+.1f}p)</span></div>',
                    unsafe_allow_html=True,
                )

    # ── Storico trade + statistiche
    if history:
        st.markdown("---")
        wins     = [t for t in history if t.get("pnl", 0) > 0]
        losses   = [t for t in history if t.get("pnl", 0) <= 0]
        total_h  = len(history)
        wr       = len(wins) / total_h * 100 if total_h else 0
        avg_win  = np.mean([t["pnl"] for t in wins])   if wins   else 0.0
        avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0.0
        pf       = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)) if losses else float("inf")
        tot_pnl  = sum(t.get("pnl", 0) for t in history)

        stat_cols = st.columns(6)
        stat_cols[0].metric("Trade chiusi", total_h)
        stat_cols[1].metric("Win Rate",     f"{wr:.1f}%")
        stat_cols[2].metric("Profit Factor", f"{pf:.2f}" if pf != float("inf") else "∞")
        stat_cols[3].metric("Avg Win",      f"{avg_win:+.2f} €")
        stat_cols[4].metric("Avg Loss",     f"{avg_loss:+.2f} €")
        stat_cols[5].metric("P&L totale",   f"{tot_pnl:+.2f} €",
                            delta_color="normal" if tot_pnl >= 0 else "inverse")

        with st.expander(f"📋 Storico trade ({total_h})", expanded=False):
            df_hist = pd.DataFrame(history[:100])
            show_cols = [c for c in ["time", "type", "direction", "entry", "exit", "lot", "pips", "pnl"] if c in df_hist.columns]

            def style_row(row):
                color = "#22c55e" if row.get("pnl", 0) > 0 else ("#ef4444" if row.get("pnl", 0) < 0 else "#f59e0b")
                return [f"color: {color}"] * len(row)

            st.dataframe(
                df_hist[show_cols].style.apply(style_row, axis=1),
                use_container_width=True,
                height=min(400, 45 + len(df_hist) * 35),
            )

    # ── Auto-advance
    if ss.sim_running:
        ticks = SIM_TICK_RATE * ss.sim_speed
        advance_sim(ticks_to_generate=ticks)
        time.sleep(1)
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
init_sim()
render()
