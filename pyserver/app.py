from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

APP_ROOT = Path(__file__).resolve().parent.parent
DIST_PATH = APP_ROOT / 'dist'
PORT = int(os.getenv('PORT', '8787'))
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'anthropic/claude-sonnet-4.6')

app = FastAPI(title='bot_trading python api')


def normalize_symbol(value: str) -> str:
    return value.strip().upper() or 'SXR8.DE'


def build_news_query(symbol: str) -> str:
    queries = {
        'SXR8.DE': 'S&P 500 stock market',
        'IS3N.DE': 'MSCI Emerging Markets stock market',
        'EXSA.DE': 'STOXX Europe 600 stock market',
        'BTC-USD': 'BTC OR Bitcoin crypto market',
        'ETH-USD': 'ETH OR Ethereum crypto market',
        '^GSPC': 'S&P 500 stock market',
    }
    return queries.get(symbol, f'{symbol} stock market finance')


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) <= period:
        return 50.0

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        delta = closes[index] - closes[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))

    average_gain = average(gains)
    average_loss = average(losses)

    for index in range(period + 1, len(closes)):
        delta = closes[index] - closes[index - 1]
        gain = max(delta, 0.0)
        loss = abs(min(delta, 0.0))
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period

    if average_loss == 0:
        return 100.0

    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def compute_market_stats(points: list[dict[str, float | str]]) -> dict[str, float]:
    closes = [float(point['close']) for point in points]
    volumes = [float(point['volume']) for point in points if float(point['volume']) > 0]
    latest_close = closes[-1]
    base_close = closes[0]
    moving_average_window = closes[-50:]
    latest_twenty_volumes = volumes[-20:]
    moving_average_50 = average(moving_average_window)
    average_volume_20 = average(latest_twenty_volumes)
    latest_volume = float(points[-1]['volume']) if points else 0.0

    return {
        'latestClose': latest_close,
        'changePercent': 0.0 if base_close == 0 else ((latest_close - base_close) / base_close) * 100,
        'movingAverage50': moving_average_50,
        'high52w': max(closes),
        'low52w': min(closes),
        'averageVolume20': average_volume_20,
        'rsi14': compute_rsi(closes),
        'priceVsMa50Percent': 0.0 if moving_average_50 == 0 else ((latest_close - moving_average_50) / moving_average_50) * 100,
        'volumeRatio20': 0.0 if average_volume_20 == 0 else latest_volume / average_volume_20,
    }


def fetch_yahoo_chart(symbol: str, range_value: str, interval: str) -> dict[str, Any]:
    response = requests.get(
        f'https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}',
        params={
            'range': range_value,
            'interval': interval,
            'includePrePost': 'false',
            'events': 'div,splits',
        },
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
        },
        timeout=20,
    )

    if not response.ok:
        raise HTTPException(status_code=502, detail=f'Yahoo Finance a repondu {response.status_code}.')

    payload = response.json()
    result = payload.get('chart', {}).get('result', [None])[0]
    if not result or not result.get('timestamp') or not result.get('indicators', {}).get('quote'):
        message = payload.get('chart', {}).get('error', {}).get('description') or 'Flux de marche indisponible pour ce symbole.'
        raise HTTPException(status_code=502, detail=message)

    return result


def fetch_market_data(symbol: str, range_value: str, interval: str) -> dict[str, Any]:
    result = fetch_yahoo_chart(symbol, range_value, interval)
    quote = result['indicators']['quote'][0]
    points: list[dict[str, float | str]] = []

    for index, timestamp in enumerate(result['timestamp']):
        open_price = quote.get('open', [None])[index]
        high_price = quote.get('high', [None])[index]
        low_price = quote.get('low', [None])[index]
        close_price = quote.get('close', [None])[index]
        volume = quote.get('volume', [0])[index] or 0

        raw_values = [open_price, high_price, low_price, close_price]
        if any(value is None or (isinstance(value, float) and math.isnan(value)) for value in raw_values):
            continue

        points.append(
            {
                'time': __import__('datetime').datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d'),
                'open': float(open_price),
                'high': float(high_price),
                'low': float(low_price),
                'close': float(close_price),
                'volume': float(volume),
            }
        )

    if not points:
        raise HTTPException(status_code=502, detail='Aucune bougie exploitable retournee par Yahoo Finance.')

    meta = result.get('meta', {})
    stats = compute_market_stats(points)

    return {
        'symbol': symbol,
        'currency': meta.get('currency', 'USD'),
        'exchangeName': meta.get('exchangeName', 'Market'),
        'regularMarketPrice': float(meta.get('regularMarketPrice', stats['latestClose'])),
        'points': points,
        'stats': stats,
    }


def fetch_news_items(symbol: str) -> list[dict[str, str]]:
    response = requests.get(
        'https://news.google.com/rss/search',
        params={
            'q': build_news_query(symbol),
            'hl': 'fr',
            'gl': 'FR',
            'ceid': 'FR:fr',
        },
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8',
        },
        timeout=20,
    )

    if not response.ok:
        raise HTTPException(status_code=502, detail=f'Google News a repondu {response.status_code}.')

    root = ElementTree.fromstring(response.text)
    items: list[dict[str, str]] = []
    for item in root.findall('./channel/item')[:8]:
        title = (item.findtext('title') or 'Sans titre').replace(' - Google News', '')
        link = item.findtext('link') or '#'
        source = item.findtext('source') or 'Google News'
        published = item.findtext('pubDate') or 'Date inconnue'
        items.append(
            {
                'title': title,
                'link': link,
                'source': source,
                'published': published,
            }
        )

    return items


def heuristic_news_analysis(symbol: str, items: list[dict[str, str]]) -> dict[str, Any]:
    positive_keywords = {
        'beat', 'beats', 'upgrade', 'upgrades', 'growth', 'record', 'surge', 'rally', 'expansion', 'bull', 'gain', 'positive', 'strong'
    }
    negative_keywords = {
        'miss', 'downgrade', 'downgrades', 'fall', 'drops', 'drop', 'slump', 'risk', 'warning', 'bear', 'loss', 'negative', 'weak'
    }

    score = 0
    drivers: list[str] = []
    for item in items[:5]:
        normalized = item['title'].lower()
        positive_hits = sum(keyword in normalized for keyword in positive_keywords)
        negative_hits = sum(keyword in normalized for keyword in negative_keywords)
        score += positive_hits - negative_hits
        if positive_hits > negative_hits:
            drivers.append(f"Headline positive: {item['title']}")
        elif negative_hits > positive_hits:
            drivers.append(f"Headline negative: {item['title']}")

    sentiment = clamp(score / max(len(items[:5]), 1), -1.0, 1.0)
    action_bias = 'legerement haussier' if sentiment > 0.15 else 'legerement baissier' if sentiment < -0.15 else 'neutre'

    return {
        'sentiment': sentiment,
        'confidence': int(clamp(45 + abs(sentiment) * 35, 35, 80)),
        'summary': f"Lecture news pour {symbol}: flux {action_bias} sur les derniers titres Google News.",
        'drivers': drivers[:3] or ['Peu de signaux textuels forts dans les headlines recentes.'],
        'llmUsed': False,
        'model': 'heuristic-fallback',
    }


def extract_json_object(content: str) -> dict[str, Any] | None:
    match = re.search(r'\{.*\}', content, flags=re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


def request_openrouter_analysis(symbol: str, items: list[dict[str, str]]) -> dict[str, Any]:
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key or not items:
        return heuristic_news_analysis(symbol, items)

    headlines_block = '\n'.join(f"- {item['title']} ({item['source']})" for item in items[:5])
    payload = {
        'model': OPENROUTER_MODEL,
        'temperature': 0.2,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'Tu es un analyste buy-side prudent. Reponds en JSON strict avec les cles '
                    'sentiment, confidence, summary, drivers. '
                    'sentiment doit etre compris entre -1 et 1, confidence entre 0 et 100, '
                    'summary en francais sur une phrase, drivers tableau de 3 phrases maximum.'
                ),
            },
            {
                'role': 'user',
                'content': (
                    f'Analyse ces news recentes sur {symbol}:\n{headlines_block}\n\n'
                    'Retourne uniquement un objet JSON.'
                ),
            },
        ],
    }

    try:
        response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:5173',
                'X-Title': 'bot_trading',
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        parsed = extract_json_object(content if isinstance(content, str) else json.dumps(content))
        if not parsed:
            raise ValueError('OpenRouter JSON parsing failed')

        sentiment = clamp(float(parsed.get('sentiment', 0.0)), -1.0, 1.0)
        confidence = int(clamp(float(parsed.get('confidence', 55)), 0, 100))
        summary = str(parsed.get('summary', 'Lecture news disponible.'))
        drivers = parsed.get('drivers', [])
        if not isinstance(drivers, list):
            drivers = [str(drivers)]

        return {
            'sentiment': sentiment,
            'confidence': confidence,
            'summary': summary,
            'drivers': [str(driver) for driver in drivers[:3]],
            'llmUsed': True,
            'model': OPENROUTER_MODEL,
        }
    except Exception:
        return heuristic_news_analysis(symbol, items)


def build_news_summary(symbol: str, items: list[dict[str, str]]) -> str | None:
    if not items:
        return None

    bullet_points = [f"- {item['title']}" for item in items[:3]]
    latest_source = items[0]['source'] if items else 'Google News'
    return '\n'.join(
        [
            f'Synthese rapide pour {symbol} :',
            *bullet_points,
            f'Impact potentiel: sentiment de marche a confirmer avec les prix et volumes. Source dominante: {latest_source}.',
        ]
    )


def build_technical_signal(market: dict[str, Any]) -> dict[str, Any]:
    stats = market['stats']
    price_vs_ma = float(stats['priceVsMa50Percent'])
    rsi = float(stats['rsi14'])
    change_percent = float(stats['changePercent'])
    volume_ratio = float(stats['volumeRatio20'])
    high_52w = float(stats['high52w'])
    low_52w = float(stats['low52w'])
    latest_close = float(stats['latestClose'])

    score = 0.0
    drivers: list[str] = []

    if price_vs_ma > 1.5:
        score += 0.35
        drivers.append('Prix au-dessus de la moyenne mobile 50 jours.')
    elif price_vs_ma < -1.5:
        score -= 0.35
        drivers.append('Prix sous la moyenne mobile 50 jours.')
    else:
        drivers.append('Prix proche de la moyenne mobile 50 jours.')

    if rsi < 35:
        score += 0.15
        drivers.append('RSI survendu, possible rebond technique.')
    elif rsi > 70:
        score -= 0.15
        drivers.append('RSI tendu, risque de respiration.')
    else:
        score += 0.05
        drivers.append('RSI neutre a constructif.')

    if change_percent > 4:
        score += 0.2
        drivers.append('Momentum recent haussier.')
    elif change_percent < -4:
        score -= 0.2
        drivers.append('Momentum recent baissier.')

    if volume_ratio > 1.15 and change_percent > 0:
        score += 0.1
        drivers.append('Hausse confirmee par les volumes.')
    elif volume_ratio > 1.15 and change_percent < 0:
        score -= 0.1
        drivers.append('Baisse confirmee par les volumes.')

    range_span = max(high_52w - low_52w, 1e-9)
    position_in_range = (latest_close - low_52w) / range_span
    if position_in_range > 0.8:
        score += 0.1
        drivers.append('Cours proche du haut de range annuel.')
    elif position_in_range < 0.2:
        score -= 0.1
        drivers.append('Cours proche du bas de range annuel.')

    confidence = int(clamp(48 + abs(score) * 32, 40, 85))

    return {
        'score': clamp(score, -1.0, 1.0),
        'confidence': confidence,
        'drivers': drivers[:4],
    }


def build_trade_signal(symbol: str, market: dict[str, Any], news_items: list[dict[str, str]]) -> dict[str, Any]:
    technical = build_technical_signal(market)
    news = request_openrouter_analysis(symbol, news_items)
    combined_score = clamp((technical['score'] * 0.6) + (float(news['sentiment']) * 0.4), -1.0, 1.0)

    if combined_score >= 0.2:
        action = 'buy'
        label = 'Acheter'
    elif combined_score <= -0.2:
        action = 'sell'
        label = 'Vendre'
    else:
        action = 'hold'
        label = 'Conserver'

    confidence = int(
        clamp(
            42 + abs(combined_score) * 28 + (technical['confidence'] * 0.15) + (int(news['confidence']) * 0.15),
            35,
            95,
        )
    )

    summary = (
        f"{label} avec un indice de confiance de {confidence}/100. "
        f"Technique {technical['score']:+.2f}, news {float(news['sentiment']):+.2f}. {news['summary']}"
    )

    return {
        'symbol': symbol,
        'action': action,
        'label': label,
        'confidence': confidence,
        'score': round(combined_score, 3),
        'summary': summary,
        'technicalScore': round(float(technical['score']), 3),
        'newsScore': round(float(news['sentiment']), 3),
        'technicalConfidence': int(technical['confidence']),
        'newsConfidence': int(news['confidence']),
        'technicalDrivers': technical['drivers'],
        'newsDrivers': news['drivers'],
        'llmUsed': bool(news['llmUsed']),
        'model': news['model'],
    }


@app.get('/api/health')
def health() -> dict[str, bool]:
    return {'ok': True}


@app.get('/api/market')
def market(symbol: str = 'SXR8.DE', range: str = '1y', interval: str = '1d') -> dict[str, Any]:
    return fetch_market_data(normalize_symbol(symbol), range, interval)


@app.get('/api/news')
def news(symbol: str = 'SXR8.DE') -> dict[str, Any]:
    normalized = normalize_symbol(symbol)
    items = fetch_news_items(normalized)
    return {
        'symbol': normalized,
        'source': 'Google News',
        'summary': build_news_summary(normalized, items),
        'items': items,
    }


@app.get('/api/signal')
def signal(symbol: str = 'SXR8.DE', range: str = '1y', interval: str = '1d') -> dict[str, Any]:
    normalized = normalize_symbol(symbol)
    market_payload = fetch_market_data(normalized, range, interval)
    news_items = fetch_news_items(normalized)
    return build_trade_signal(normalized, market_payload, news_items)


if DIST_PATH.exists():
    app.mount('/assets', StaticFiles(directory=DIST_PATH / 'assets'), name='assets')


@app.get('/')
def index() -> FileResponse:
    if not (DIST_PATH / 'index.html').exists():
        raise HTTPException(status_code=404, detail='Frontend build not found.')
    return FileResponse(DIST_PATH / 'index.html')


@app.get('/{full_path:path}')
def spa_fallback(full_path: str) -> FileResponse:
    candidate = DIST_PATH / full_path
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    if not (DIST_PATH / 'index.html').exists():
        raise HTTPException(status_code=404, detail='Frontend build not found.')
    return FileResponse(DIST_PATH / 'index.html')


if __name__ == '__main__':
    uvicorn.run('pyserver.app:app', host='0.0.0.0', port=PORT, reload=False)