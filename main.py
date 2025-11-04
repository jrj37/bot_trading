# data.py
import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import os
import datetime

def download_btc(start="2025-01-01", end=None, interval="1h", save_csv="btc_usd_1h.csv"):
    if end is None:
        end = datetime.datetime.now().strftime("%Y-%m-%d")
    print(f"Downloading BTC-USD from {start} to {end} interval={interval} ...")
    df = yf.download("BTC-USD", start=start, end=end, interval=interval, progress=False)
    if df.empty:
        raise RuntimeError("Aucune donnée téléchargée : vérifie l'intervalle ou la connexion.")
    df = df[['Open','High','Low','Close','Volume']]
    df.to_csv(save_csv)
    print(f"Saved -> {save_csv}")
    return df


download_btc()