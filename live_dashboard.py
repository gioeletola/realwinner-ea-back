"""
RealWinner EA v5 — Live Dashboard
Streamlit app che si connette a MT5 e mostra segnali + posizioni in tempo reale.

Avvio:
    pip install -r requirements.txt
    streamlit run live_dashboard.py
"""

import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# ─────────────────────────────────────────────────────────────────────────────
# ALERT SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

ALERT_SOUND_LONG = """
<audio autoplay>
  <source src="data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAA..." type="audio/wav">
</audio>
"""

def init_alert_state():
    if "alert_history" not in st.session_state:
        st.session_state.alert_history = []
    if "last_signal" not in st.session_state:
        st.session_state.last_signal = 0
    if "last_dd_alert" not in st.session_state:
        st.session_state.last_dd_alert = 0.0
    if "alerts_enabled" not in st.session_state:
        st.session_state.alerts_enabled = True


def push_alert(level: str, title: str, message: str):
    """Aggiunge un alert allo storico e mostra toast."""
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    st.session_state.alert_history.insert(0, {
        "time": now,
        "level": level,
        "title": title,
        "message": message,
    })
    # Mantieni max 50 alert
    st.session_state.alert_history = st.session_state.alert_history[:50]
    # Toast Streamlit
    if level == "success":
        st.toast(f"🟢 {title}: {message}", icon="📈")
    elif level == "error":
        st.toast(f"🔴 {title}: {message}", icon="⚠️")
    elif level == "warning":
        st.toast(f"🟡 {title}: {message}", icon="🔔")
    else:
        st.toast(f"ℹ️ {title}: {message}")


def check_signal_alert(sig: dict):
    """Lancia alert se il segnale cambia da FLAT a LONG/SHORT."""
    if not st.session_state.alerts_enabled:
        return
    prev = st.session_state.last_signal
    curr = sig["signal"]
    if curr != prev:
        if curr == 1:
            push_alert("success", "SEGNALE LONG", f"SMC:{sig['smc']} Trend:{sig['trend']} MR:{sig['mr']} — Confluenza {sig['bull']}▲")
        elif curr == -1:
            push_alert("error", "SEGNALE SHORT", f"SMC:{sig['smc']} Trend:{sig['trend']} MR:{sig['mr']} — Confluenza {sig['bear']}▼")
        elif curr == 0 and prev != 0:
            push_alert("info", "Segnale chiuso", "Tornato in FLAT")
    st.session_state.last_signal = curr


def check_dd_alert(dd_pct: float, max_daily_loss: float, daily_warning: float):
    """Alert se drawdown supera soglie."""
    if not st.session_state.alerts_enabled:
        return
    prev = st.session_state.last_dd_alert
    if dd_pct >= max_daily_loss and prev < max_daily_loss:
        push_alert("error", "MAX DAILY LOSS RAGGIUNTO", f"DD {dd_pct:.2f}% ≥ {max_daily_loss}% — EA bloccato!")
    elif dd_pct >= daily_warning and prev < daily_warning:
        push_alert("warning", "Daily Warning", f"DD {dd_pct:.2f}% ≥ {daily_warning}% — lot size dimezzato")
    st.session_state.last_dd_alert = dd_pct


def render_alert_panel():
    """Pannello storico alert nella sidebar."""
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔔 Alert")
    st.session_state.alerts_enabled = st.sidebar.toggle(
        "Alert attivi", value=st.session_state.get("alerts_enabled", True)
    )

    history = st.session_state.get("alert_history", [])
    if not history:
        st.sidebar.caption("Nessun alert ancora.")
        return

    if st.sidebar.button("🗑️ Cancella storico"):
        st.session_state.alert_history = []
        st.rerun()

    for a in history[:10]:
        icon = {"success": "🟢", "error": "🔴", "warning": "🟡"}.get(a["level"], "ℹ️")
        st.sidebar.markdown(
            f"{icon} **{a['time']}** — {a['title']}  \n"
            f"<small>{a['message']}</small>",
            unsafe_allow_html=True,
        )

# MetaTrader5 è disponibile solo su Windows; su Linux/Mac si usa la modalità demo
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RealWinner EA v5 — Live",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# STILE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background: #1e1e2e;
        border-radius: 10px;
        padding: 12px 16px;
        border-left: 4px solid #7c3aed;
    }
    .signal-bull { color: #22c55e; font-weight: 700; font-size: 1.1em; }
    .signal-bear { color: #ef4444; font-weight: 700; font-size: 1.1em; }
    .signal-flat { color: #94a3b8; font-weight: 700; font-size: 1.1em; }
    .status-ok   { color: #22c55e; }
    .status-warn { color: #f59e0b; }
    .status-stop { color: #ef4444; }
    div[data-testid="stMetricValue"] { font-size: 1.4em; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETRI EA (devono corrispondere agli input MQL5)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = dict(
    use_smc=True, use_trend=True, use_mr=True, confluence_min=2,
    ema_fast=9, ema_med=21, ema_slow=50, ema_200=200,
    rsi_period=14,
    rsi_long_min=50, rsi_long_max=78,
    rsi_short_min=22, rsi_short_max=50,
    bb_period=20, bb_dev=2.0,
    mr_overbought=70, mr_oversold=30,
    atr_period=14, atr_sl_mult=1.1,
    ob_lookback=50, ob_strength=2, ob_body_min=0.00010,
    tp1_rr=1.5, tp2_rr=3.0,
    risk_pct=0.9,
    max_daily_loss=2.4, daily_warning=0.7, max_total_dd=5.5,
    max_trades_day=10, max_consec_loss=3,
    london_open=7, london_close=11,
    ny_open=13, ny_close=18,
    overlap_open=11, overlap_close=13,
)

# ─────────────────────────────────────────────────────────────────────────────
# INDICATORI (port Python da MQL5)
# ─────────────────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def bollinger(series: pd.Series, period: int, dev: float):
    mid   = series.rolling(period).mean()
    std   = series.rolling(period).std()
    upper = mid + dev * std
    lower = mid - dev * std
    return upper, mid, lower


def compute_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    c = df["close"].copy()
    df["ema_fast"]  = ema(c, p["ema_fast"])
    df["ema_med"]   = ema(c, p["ema_med"])
    df["ema_slow"]  = ema(c, p["ema_slow"])
    df["ema_200"]   = ema(c, p["ema_200"])
    df["rsi"]       = rsi(c, p["rsi_period"])
    df["atr"]       = atr(df, p["atr_period"])
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger(c, p["bb_period"], p["bb_dev"])
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL ENGINE (fedele all'MQL5)
# ─────────────────────────────────────────────────────────────────────────────

def get_htf_bias(df_h4: pd.DataFrame, p: dict) -> int:
    """Ritorna +1 (bullish) / -1 (bearish) / 0 sul timeframe H4."""
    if df_h4 is None or len(df_h4) < p["ema_200"]:
        return 0
    row = df_h4.iloc[-2]  # barra chiusa
    fast = row["ema_fast"]
    slow = row["ema_slow"]
    e200 = row["ema_200"]
    price = row["close"]
    if fast > slow and price > e200:
        return 1
    if fast < slow and price < e200:
        return -1
    return 0


def get_smc_signal(df: pd.DataFrame, p: dict, htf_bias: int) -> int:
    if not p["use_smc"] or htf_bias == 0:
        return 0

    n = len(df)
    if n < p["ob_lookback"] + 5:
        return 0

    # Break of Structure (ultimi 30 bar)
    window = df.iloc[-31:-1]
    swing_high = window["high"].max()
    swing_low  = window["low"].min()
    cur_close  = df["close"].iloc[-2]

    bos_bull = (cur_close > swing_high) and (htf_bias == 1)
    bos_bear = (cur_close < swing_low)  and (htf_bias == -1)

    # Order Blocks
    ob_bull = ob_bear = False
    ob_window = df.iloc[-(p["ob_lookback"] + p["ob_strength"] + 2):-1]
    opens  = ob_window["open"].values
    closes = ob_window["close"].values
    strength = p["ob_strength"]

    for i in range(strength, len(closes) - strength):
        body = abs(closes[i] - opens[i])
        if body < p["ob_body_min"]:
            continue
        # Bearish OB → impulso rialzista → long
        if closes[i] < opens[i]:
            if all(closes[i - j - 1] > opens[i - j - 1] for j in range(strength)):
                if htf_bias == 1:
                    ob_bull = True
        # Bullish OB → impulso ribassista → short
        if closes[i] > opens[i]:
            if all(closes[i - j - 1] < opens[i - j - 1] for j in range(strength)):
                if htf_bias == -1:
                    ob_bear = True

    if (bos_bull or ob_bull) and htf_bias == 1:
        return 1
    if (bos_bear or ob_bear) and htf_bias == -1:
        return -1
    return 0


def get_trend_signal(df: pd.DataFrame, p: dict) -> int:
    if not p["use_trend"] or len(df) < p["ema_200"] + 5:
        return 0
    row = df.iloc[-2]
    ef, em, es, e200 = row["ema_fast"], row["ema_med"], row["ema_slow"], row["ema_200"]
    r, price = row["rsi"], row["close"]

    trend_long  = ef > em > es and price > e200 and p["rsi_long_min"]  <= r <= p["rsi_long_max"]
    trend_short = ef < em < es and price < e200 and p["rsi_short_min"] <= r <= p["rsi_short_max"]

    if trend_long:  return 1
    if trend_short: return -1
    return 0


def get_mr_signal(df: pd.DataFrame, p: dict) -> int:
    if not p["use_mr"] or len(df) < p["bb_period"] + 5:
        return 0
    row = df.iloc[-2]
    ema_spread = abs(row["ema_fast"] - row["ema_slow"])
    if ema_spread > 0.0020:
        return 0  # mercato in trend → skip MR
    price = row["close"]
    r     = row["rsi"]
    if price <= row["bb_lower"] and r <= p["mr_oversold"]:
        return 1
    if price >= row["bb_upper"] and r >= p["mr_overbought"]:
        return -1
    return 0


def get_confluence_signal(df: pd.DataFrame, df_h4: pd.DataFrame, p: dict) -> dict:
    htf_bias = get_htf_bias(df_h4, p)
    smc   = get_smc_signal(df, p, htf_bias)
    trend = get_trend_signal(df, p)
    mr    = get_mr_signal(df, p)

    bull = (smc == 1) + (trend == 1) + (mr == 1)
    bear = (smc == -1) + (trend == -1) + (mr == -1)

    if bull >= p["confluence_min"]:
        signal = 1
    elif bear >= p["confluence_min"]:
        signal = -1
    else:
        signal = 0

    return dict(signal=signal, smc=smc, trend=trend, mr=mr,
                htf_bias=htf_bias, bull=bull, bear=bear)


# ─────────────────────────────────────────────────────────────────────────────
# MT5 CONNECTION
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def init_mt5(server: str, login: int, password: str):
    if not MT5_AVAILABLE:
        return False, "MetaTrader5 package non disponibile (solo Windows)"
    if not mt5.initialize(server=server, login=login, password=password):
        err = mt5.last_error()
        mt5.shutdown()
        return False, f"Connessione fallita: {err}"
    return True, "Connesso"


def fetch_bars_mt5(symbol: str, timeframe, n_bars: int) -> pd.DataFrame | None:
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_bars)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})[["time","open","high","low","close","volume"]]
    return df.reset_index(drop=True)


def get_account_info() -> dict:
    if not MT5_AVAILABLE:
        return {}
    info = mt5.account_info()
    if info is None:
        return {}
    return info._asdict()


def get_open_positions(symbol: str) -> pd.DataFrame:
    if not MT5_AVAILABLE:
        return pd.DataFrame()
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return pd.DataFrame()
    rows = []
    for p in positions:
        rows.append({
            "Ticket":  p.ticket,
            "Type":    "BUY" if p.type == 0 else "SELL",
            "Volume":  p.volume,
            "Open":    p.price_open,
            "Current": p.price_current,
            "SL":      p.sl,
            "TP":      p.tp,
            "Profit":  round(p.profit, 2),
            "Comment": p.comment,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# DEMO DATA (quando MT5 non è disponibile)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=900)
def generate_demo_bars(n: int = 500, seed: int = 42) -> pd.DataFrame:
    rng  = np.random.default_rng(seed)
    now  = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    # arrotonda a 15 min
    now  = now - timedelta(minutes=now.minute % 15)
    times = [now - timedelta(minutes=15 * i) for i in range(n)][::-1]
    price = 1.0800
    rows  = []
    for t in times:
        o = price
        c = o + rng.normal(0, 0.0003)
        h = max(o, c) + abs(rng.normal(0, 0.0001))
        l = min(o, c) - abs(rng.normal(0, 0.0001))
        v = int(rng.integers(500, 3000))
        rows.append(dict(time=t, open=round(o,5), high=round(h,5),
                         low=round(l,5), close=round(c,5), volume=v))
        price = c
    return pd.DataFrame(rows)


def generate_demo_h4(df_m15: pd.DataFrame) -> pd.DataFrame:
    df = df_m15.copy()
    df["bar_h4"] = df["time"].dt.floor("4h")
    g = df.groupby("bar_h4").agg(
        time=("bar_h4", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index(drop=True)
    return g


# ─────────────────────────────────────────────────────────────────────────────
# CHART
# ─────────────────────────────────────────────────────────────────────────────

def build_chart(df: pd.DataFrame, signal_info: dict, n_candles: int = 120) -> go.Figure:
    df_plot = df.tail(n_candles).copy()

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20],
        vertical_spacing=0.03,
        subplot_titles=("EURUSD M15", "RSI", "ATR"),
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df_plot["time"],
        open=df_plot["open"], high=df_plot["high"],
        low=df_plot["low"],   close=df_plot["close"],
        name="Price", increasing_line_color="#22c55e",
        decreasing_line_color="#ef4444", showlegend=False,
    ), row=1, col=1)

    # EMAs
    ema_configs = [
        ("ema_fast",  "#60a5fa", f"EMA {DEFAULT_PARAMS['ema_fast']}"),
        ("ema_med",   "#a78bfa", f"EMA {DEFAULT_PARAMS['ema_med']}"),
        ("ema_slow",  "#f59e0b", f"EMA {DEFAULT_PARAMS['ema_slow']}"),
        ("ema_200",   "#f43f5e", f"EMA {DEFAULT_PARAMS['ema_200']}"),
    ]
    for col_name, color, label in ema_configs:
        if col_name in df_plot.columns:
            fig.add_trace(go.Scatter(
                x=df_plot["time"], y=df_plot[col_name],
                line=dict(color=color, width=1),
                name=label, showlegend=True,
            ), row=1, col=1)

    # Bollinger Bands
    if "bb_upper" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot["time"], y=df_plot["bb_upper"],
            line=dict(color="rgba(148,163,184,0.4)", width=1, dash="dot"),
            name="BB Upper", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df_plot["time"], y=df_plot["bb_lower"],
            line=dict(color="rgba(148,163,184,0.4)", width=1, dash="dot"),
            fill="tonexty", fillcolor="rgba(148,163,184,0.05)",
            name="BB Lower", showlegend=False,
        ), row=1, col=1)

    # Segnale corrente — freccia verticale sull'ultima barra
    last_time  = df_plot["time"].iloc[-1]
    last_close = df_plot["close"].iloc[-1]
    sig = signal_info.get("signal", 0)
    if sig == 1:
        fig.add_annotation(
            x=last_time, y=last_close, text="▲ LONG",
            showarrow=True, arrowhead=2, arrowcolor="#22c55e",
            font=dict(color="#22c55e", size=14),
            row=1, col=1,
        )
    elif sig == -1:
        fig.add_annotation(
            x=last_time, y=last_close, text="▼ SHORT",
            showarrow=True, arrowhead=2, arrowcolor="#ef4444",
            font=dict(color="#ef4444", size=14),
            row=1, col=1,
        )

    # RSI
    if "rsi" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot["time"], y=df_plot["rsi"],
            line=dict(color="#a78bfa", width=1.5),
            name="RSI", showlegend=False,
        ), row=2, col=1)
        for lvl, color in [(70, "rgba(239,68,68,0.3)"), (30, "rgba(34,197,94,0.3)"), (50, "rgba(148,163,184,0.2)")]:
            fig.add_hline(y=lvl, line=dict(color=color, width=1, dash="dash"), row=2, col=1)

    # ATR
    if "atr" in df_plot.columns:
        fig.add_trace(go.Bar(
            x=df_plot["time"], y=df_plot["atr"],
            marker_color="#7c3aed", opacity=0.7,
            name="ATR", showlegend=False,
        ), row=3, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=600,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

def sidebar():
    st.sidebar.title("⚙️ Configurazione")

    mode = st.sidebar.radio(
        "Modalità",
        ["Demo (dati sintetici)", "Live MT5"],
        help="Demo non richiede MT5 installato",
    )

    symbol = st.sidebar.text_input("Simbolo", "EURUSD")
    n_candles = st.sidebar.slider("Candele grafico", 50, 300, 120, step=10)
    refresh_sec = st.sidebar.slider("Aggiornamento (sec)", 15, 300, 60, step=15)

    conn = {"mode": mode, "symbol": symbol, "n_candles": n_candles, "refresh_sec": refresh_sec}

    if mode == "Live MT5":
        st.sidebar.markdown("---")
        st.sidebar.subheader("Credenziali MT5")
        conn["server"]   = st.sidebar.text_input("Server", placeholder="ICMarkets-Demo")
        conn["login"]    = st.sidebar.number_input("Login", value=0, min_value=0)
        conn["password"] = st.sidebar.text_input("Password", type="password")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Parametri EA")
    p = DEFAULT_PARAMS.copy()
    p["use_smc"]       = st.sidebar.checkbox("SMC",           value=True)
    p["use_trend"]     = st.sidebar.checkbox("Trend",         value=True)
    p["use_mr"]        = st.sidebar.checkbox("Mean Reversion",value=True)
    p["confluence_min"]= st.sidebar.selectbox("Confluenza min", [1, 2, 3], index=1)
    p["risk_pct"]      = st.sidebar.slider("Rischio %", 0.1, 3.0, 0.9, step=0.1)

    return conn, p


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def signal_badge(val: int) -> str:
    if val == 1:
        return '<span class="signal-bull">▲ LONG</span>'
    if val == -1:
        return '<span class="signal-bear">▼ SHORT</span>'
    return '<span class="signal-flat">— FLAT</span>'


def main():
    st.title("📈 RealWinner EA v5 — Live Monitor")

    init_alert_state()
    conn, p = sidebar()
    render_alert_panel()
    symbol = conn["symbol"]
    demo_mode = conn["mode"] == "Demo (dati sintetici)"

    # ── Connessione MT5
    connected = False
    if not demo_mode:
        if not MT5_AVAILABLE:
            st.error("❌ MetaTrader5 non installato. Usa `pip install MetaTrader5` (solo Windows).")
            st.info("Passa alla modalità Demo per testare senza MT5.")
            return
        ok, msg = init_mt5(conn.get("server",""), int(conn.get("login",0)), conn.get("password",""))
        if not ok:
            st.error(f"❌ {msg}")
            return
        connected = True
        st.success(f"✅ Connesso a MT5 — {conn.get('server','')}")

    # ── Fetch dati
    if connected:
        TF_M15 = mt5.TIMEFRAME_M15
        TF_H4  = mt5.TIMEFRAME_H4
        df_m15 = fetch_bars_mt5(symbol, TF_M15, 600)
        df_h4  = fetch_bars_mt5(symbol, TF_H4,  300)
        acct   = get_account_info()
    else:
        # Demo
        df_m15 = generate_demo_bars(600)
        df_h4  = generate_demo_h4(df_m15)
        acct   = {
            "balance": 10000.0, "equity": 10125.0,
            "profit": 125.0, "currency": "USD",
            "leverage": 100, "login": 99999999,
        }

    if df_m15 is None or len(df_m15) < 50:
        st.error("Dati insufficienti. Controlla simbolo e connessione.")
        return

    # ── Calcola indicatori
    df_m15 = compute_indicators(df_m15.copy(), p)
    df_h4  = compute_indicators(df_h4.copy(), p)

    # ── Calcola segnali
    sig = get_confluence_signal(df_m15, df_h4, p)

    # ── Controlla alert
    check_signal_alert(sig)

    # ─────────────────────────────────────────────────────────────
    # ROW 1 — Account info
    # ─────────────────────────────────────────────────────────────
    st.markdown("### Account")
    c1, c2, c3, c4, c5 = st.columns(5)

    balance = acct.get("balance", 0)
    equity  = acct.get("equity",  0)
    profit  = acct.get("profit",  0)
    dd_pct  = (balance - equity) / balance * 100 if balance > 0 else 0
    currency = acct.get("currency", "USD")

    check_dd_alert(dd_pct, p["max_daily_loss"], p["daily_warning"])

    c1.metric("Balance",  f"{balance:,.2f} {currency}")
    c2.metric("Equity",   f"{equity:,.2f} {currency}")
    c3.metric("P&L Open", f"{profit:+.2f} {currency}",
              delta_color="normal" if profit >= 0 else "inverse")
    c4.metric("DD equity", f"{dd_pct:.2f}%",
              delta_color="inverse" if dd_pct > 0 else "normal")
    c5.metric("Login", str(acct.get("login","-")))

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────
    # ROW 2 — Segnali correnti
    # ─────────────────────────────────────────────────────────────
    st.markdown("### Segnali (ultima barra chiusa)")
    s1, s2, s3, s4, s5 = st.columns(5)

    with s1:
        st.markdown("**SMC**")
        st.markdown(signal_badge(sig["smc"]), unsafe_allow_html=True)
    with s2:
        st.markdown("**Trend**")
        st.markdown(signal_badge(sig["trend"]), unsafe_allow_html=True)
    with s3:
        st.markdown("**Mean Rev.**")
        st.markdown(signal_badge(sig["mr"]), unsafe_allow_html=True)
    with s4:
        st.markdown("**HTF Bias (H4)**")
        st.markdown(signal_badge(sig["htf_bias"]), unsafe_allow_html=True)
    with s5:
        bull_n, bear_n = sig["bull"], sig["bear"]
        conf_min = p["confluence_min"]
        color_class = "signal-bull" if sig["signal"] == 1 else \
                      "signal-bear" if sig["signal"] == -1 else "signal-flat"
        label = "▲ LONG" if sig["signal"] == 1 else \
                "▼ SHORT" if sig["signal"] == -1 else "— NESSUN SEGNALE"
        st.markdown(f"**Confluenza ({bull_n}▲ {bear_n}▼ / min {conf_min})**")
        st.markdown(f'<span class="{color_class}" style="font-size:1.3em">{label}</span>',
                    unsafe_allow_html=True)

    # ── Banner alert attivo
    if sig["signal"] == 1:
        st.success("▲ **SEGNALE LONG ATTIVO** — Confluenza raggiunta")
    elif sig["signal"] == -1:
        st.error("▼ **SEGNALE SHORT ATTIVO** — Confluenza raggiunta")

    if dd_pct >= p["max_daily_loss"]:
        st.error(f"🛑 **MAX DAILY LOSS RAGGIUNTO** — DD {dd_pct:.2f}% — EA bloccato")
    elif dd_pct >= p["daily_warning"]:
        st.warning(f"⚠️ **Daily Warning** — DD {dd_pct:.2f}% — Lot size ridotto")

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────
    # ROW 3 — Chart + Posizioni
    # ─────────────────────────────────────────────────────────────
    chart_col, pos_col = st.columns([3, 1])

    with chart_col:
        st.plotly_chart(
            build_chart(df_m15, sig, conn["n_candles"]),
            use_container_width=True,
        )

    with pos_col:
        st.markdown("### Posizioni aperte")
        if connected:
            df_pos = get_open_positions(symbol)
        else:
            # demo: nessuna posizione aperta
            df_pos = pd.DataFrame()

        if df_pos.empty:
            st.info("Nessuna posizione aperta.")
        else:
            for _, row in df_pos.iterrows():
                color = "🟢" if row["Profit"] >= 0 else "🔴"
                ptype = "▲" if row["Type"] == "BUY" else "▼"
                st.markdown(
                    f"{color} **{ptype} {row['Type']}** {row['Volume']} lot  \n"
                    f"Entry: `{row['Open']}`  Current: `{row['Current']}`  \n"
                    f"SL: `{row['SL']}`  TP: `{row['TP']}`  \n"
                    f"P&L: **{row['Profit']:+.2f}**"
                )
                st.divider()

    # ─────────────────────────────────────────────────────────────
    # ROW 4 — Ultimi valori indicatori
    # ─────────────────────────────────────────────────────────────
    st.markdown("### Indicatori (ultima barra)")
    last = df_m15.iloc[-2]
    i1, i2, i3, i4, i5, i6 = st.columns(6)
    i1.metric(f"EMA {p['ema_fast']}", f"{last.get('ema_fast', 0):.5f}")
    i2.metric(f"EMA {p['ema_slow']}", f"{last.get('ema_slow', 0):.5f}")
    i3.metric(f"EMA 200",             f"{last.get('ema_200',  0):.5f}")
    i4.metric("RSI",                  f"{last.get('rsi', 0):.1f}")
    i5.metric("ATR",                  f"{last.get('atr', 0):.5f}")
    i6.metric("BB Width",             f"{last.get('bb_upper',0) - last.get('bb_lower',0):.5f}")

    # ─────────────────────────────────────────────────────────────
    # ROW 5 — Storico alert
    # ─────────────────────────────────────────────────────────────
    history = st.session_state.get("alert_history", [])
    if history:
        with st.expander(f"🔔 Storico Alert ({len(history)})", expanded=False):
            level_colors = {"success": "#22c55e", "error": "#ef4444", "warning": "#f59e0b"}
            rows_html = ""
            for a in history:
                color = level_colors.get(a["level"], "#94a3b8")
                rows_html += (
                    f'<tr>'
                    f'<td style="color:#94a3b8;white-space:nowrap">{a["time"]}</td>'
                    f'<td style="color:{color};font-weight:700">{a["title"]}</td>'
                    f'<td style="color:#e2e8f0">{a["message"]}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<table style="width:100%;border-collapse:collapse;font-size:0.85em">'
                f'<thead><tr>'
                f'<th style="text-align:left;color:#94a3b8;padding:4px 8px">Ora</th>'
                f'<th style="text-align:left;color:#94a3b8;padding:4px 8px">Tipo</th>'
                f'<th style="text-align:left;color:#94a3b8;padding:4px 8px">Dettaglio</th>'
                f'</tr></thead><tbody>{rows_html}</tbody></table>',
                unsafe_allow_html=True,
            )

    # ─────────────────────────────────────────────────────────────
    # Footer + auto-refresh
    # ─────────────────────────────────────────────────────────────
    refresh_sec = conn["refresh_sec"]
    last_bar_time = df_m15["time"].iloc[-1]
    mode_label = "DEMO" if demo_mode else "LIVE MT5"

    st.markdown("---")
    st.caption(
        f"🕒 Ultima barra: **{last_bar_time}** UTC  |  "
        f"Modalità: **{mode_label}**  |  "
        f"Aggiornamento ogni: **{refresh_sec}s**  |  "
        f"RealWinner EA v5.0"
    )

    # Auto-refresh tramite meta-refresh HTML
    st.markdown(
        f'<meta http-equiv="refresh" content="{refresh_sec}">',
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
