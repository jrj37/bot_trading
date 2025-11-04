import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Visualisation Trading IA", layout="wide")
st.title("📊 Visualisation de données financières")

# --- Sidebar ---
st.sidebar.header("Paramètres")
ticker = st.sidebar.text_input("Symbole (ex: BTC-USD, AAPL, TSLA)", "BTC-USD")
start_date = st.sidebar.date_input("Date de début", pd.to_datetime("2025-01-01"))
end_date = st.sidebar.date_input("Date de fin", pd.to_datetime("today"))

# --- Chargement des données ---
@st.cache_data
def load_data(ticker, start, end):
    data = yf.download(ticker, start=start, end=end, auto_adjust=False)
    data.reset_index(inplace=True)

    # Aplatir les colonnes si multi-index
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] if col[1] == ticker else col[0] + "_" + col[1] for col in data.columns]

    return data

data = load_data(ticker, start_date, end_date)

if data.empty:
    st.warning("Aucune donnée trouvée pour ce symbole.")
else:
    st.subheader(f"Données pour {ticker}")
    st.dataframe(data.tail(10))

    # --- Graphique prix de clôture ---
    st.subheader("Évolution du prix de clôture")
    fig_close = px.line(
        data, x="Date_", y="Close",
        title=f"Prix de clôture de {ticker}",
        labels={"Close": "Prix de clôture", "Date": "Date"}
    )
    st.plotly_chart(fig_close, use_container_width=True)

    # --- Moyennes mobiles ---
    st.subheader("Prix avec moyennes mobiles")
    ma_short = st.sidebar.slider("MA courte", 5, 50, 20)
    ma_long = st.sidebar.slider("MA longue", 50, 200, 100)

    data["MA_Courte"] = data["Close"].rolling(ma_short).mean()
    data["MA_Longue"] = data["Close"].rolling(ma_long).mean()

    fig_ma = go.Figure()
    fig_ma.add_trace(go.Scatter(
        x=data["Date_"], y=data["Close"], mode="lines", name="Clôture", line=dict(color="blue")
    ))
    fig_ma.add_trace(go.Scatter(
        x=data["Date_"], y=data["MA_Courte"], mode="lines", name=f"MA {ma_short}", line=dict(color="orange")
    ))
    fig_ma.add_trace(go.Scatter(
        x=data["Date_"], y=data["MA_Longue"], mode="lines", name=f"MA {ma_long}", line=dict(color="green")
    ))
    fig_ma.update_layout(
        title=f"Prix avec Moyennes Mobiles - {ticker}",
        xaxis_title="Date",
        yaxis_title="Prix"
    )
    st.plotly_chart(fig_ma, use_container_width=True)

    # --- Volume ---
    st.subheader("Volume échangé")
    fig_vol = px.bar(
        data, x="Date_", y="Volume",
        labels={"Volume": "Volume échangé", "Date_": "Date"},
        title=f"Volume échangé - {ticker}"
    )
    st.plotly_chart(fig_vol, use_container_width=True)

    # --- Statistiques RSI loss etc ---
    st.subheader("Statistiques RSI")
    def compute_rsi(series, period):
        delta = series.diff(1)
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    rsi_period = st.sidebar.slider("Période RSI", 5, 30, 14)
    data["RSI"] = compute_rsi(data["Close"], rsi_period)
    st.line_chart(data.set_index("Date_")["RSI"], use_container_width=True)
    # Afficher les statistiques RSI
    st.write(data["RSI"].describe())
    # --- Statistiques MACD ---
    st.subheader("Statistiques MACD")
    def compute_macd(series, short_period=12, long_period=26, signal_period=9):
        exp1 = series.ewm(span=short_period, adjust=False).mean()
        exp2 = series.ewm(span=long_period, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        return macd, signal
    data["MACD"], data["Signal"] = compute_macd(data["Close"])
    st.write("MACD (Moving Average Convergence Divergence) :", data["MACD"].describe())
    st.write("Signal (MACD) :", data["Signal"].describe())
    # Afficher le graphique MACD
    fig_macd = go.Figure()
    fig_macd.add_trace(go.Scatter(
        x=data["Date_"], y=data["MACD"], mode="lines", name="MACD", line=dict(color="purple")
    ))
    fig_macd.add_trace(go.Scatter(
        x=data["Date_"], y=data["Signal"], mode="lines", name="Signal", line=dict(color="orange")
    ))
    fig_macd.update_layout(
        title=f"MACD - {ticker}",
        xaxis_title="Date",
        yaxis_title="MACD"
    )
    st.plotly_chart(fig_macd, use_container_width=True)
    # Stochastique : compare prix de clôture au range sur une période donnée.
    st.subheader("Statistiques Stochastiques")
    def compute_stochastic(series, period=14):
        min_val = series.rolling(window=period).min()
        max_val = series.rolling(window=period).max()
        stoch = 100 * (series - min_val) / (max_val - min_val)
        return stoch
    data["Stoch"] = compute_stochastic(data["Close"])
    st.line_chart(data.set_index("Date_")["Stoch"], use_container_width=True)
    st.write(data["Stoch"].describe())
