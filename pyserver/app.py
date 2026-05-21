from __future__ import annotations

import datetime
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(override=True)

APP_ROOT = Path(__file__).resolve().parent.parent
DIST_PATH = APP_ROOT / 'dist'
PORT = int(os.getenv('PORT', '8787'))
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'google/gemini-3.5-flash')

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
        'NVDA': 'Nvidia stock bourse',
        'TTWO': 'Take-Two Interactive stock bourse',
        'ACA.PA': 'Credit Agricole bourse action',
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


def _parse_rss_items(xml_text: str, default_source: str, limit: int = 6) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for item in root.findall('./channel/item')[:limit]:
        title = (item.findtext('title') or 'Sans titre').replace(' - Google News', '').strip()
        link = item.findtext('link') or '#'
        source = item.findtext('source') or default_source
        published = item.findtext('pubDate') or 'Date inconnue'
        items.append({'title': title, 'link': link, 'source': source, 'published': published})
    return items


def fetch_google_news(symbol: str) -> list[dict[str, str]]:
    try:
        response = requests.get(
            'https://news.google.com/rss/search',
            params={'q': build_news_query(symbol), 'hl': 'fr', 'gl': 'FR', 'ceid': 'FR:fr'},
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/rss+xml'},
            timeout=15,
        )
        if not response.ok:
            return []
        return _parse_rss_items(response.text, 'Google News', limit=6)
    except Exception as exc:
        logger.warning('Google News fetch failed for %s: %s', symbol, exc)
        return []


def _is_us_symbol(symbol: str) -> bool:
    """True for plain US tickers (NVDA, TTWO) — false for exchange-suffixed ones (IS3N.DE, ACA.PA)."""
    return '.' not in symbol and '-' not in symbol


def _relevance_keywords(symbol: str) -> set[str]:
    """Build a minimal set of terms an article title should contain to be considered relevant."""
    queries = {
        'SXR8.DE': {'s&p', 'sp500', 'sp 500', 'us stock', 'american stock', 'wall street', 'bourse américain'},
        'IS3N.DE': {'emerging', 'émergent', 'msci', 'chine', 'china', 'inde', 'india', 'brésil', 'brazil', 'asie', 'asia'},
        'EXSA.DE': {'europe', 'stoxx', 'eurostoxx', 'european stock'},
        'ACA.PA': {'crédit agricole', 'credit agricole', 'aca', 'banque'},
    }
    if symbol in queries:
        return queries[symbol]
    base = symbol.split('.')[0].split('-')[0].lower()
    return {base}


def fetch_yahoo_finance_news(symbol: str) -> list[dict[str, str]]:
    """Fetch news from Yahoo Finance JSON — only for US-listed symbols to avoid unrelated results."""
    if not _is_us_symbol(symbol):
        return []
    try:
        response = requests.get(
            'https://query1.finance.yahoo.com/v1/finance/search',
            params={'q': symbol, 'newsCount': 8, 'quotesCount': 0, 'enableFuzzyQuery': 'false'},
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
            timeout=15,
        )
        if not response.ok:
            return []
        articles = response.json().get('news', [])
        keywords = _relevance_keywords(symbol)
        items: list[dict[str, str]] = []
        for article in articles[:8]:
            title = article.get('title', 'Sans titre')
            title_lower = title.lower()
            if not any(kw in title_lower for kw in keywords):
                continue
            ts = article.get('providerPublishTime', 0)
            published = datetime.datetime.utcfromtimestamp(ts).strftime('%a, %d %b %Y %H:%M:%S +0000') if ts else 'Date inconnue'
            items.append({
                'title': title,
                'link': article.get('link', '#'),
                'source': article.get('publisher', 'Yahoo Finance'),
                'published': published,
            })
        return items
    except Exception as exc:
        logger.warning('Yahoo Finance news fetch failed for %s: %s', symbol, exc)
        return []


def fetch_yahoo_rss(symbol: str) -> list[dict[str, str]]:
    """Fetch English RSS feed from Yahoo Finance (works best for US-listed symbols)."""
    try:
        response = requests.get(
            'https://feeds.finance.yahoo.com/rss/2.0/headline',
            params={'s': symbol, 'region': 'US', 'lang': 'en-US'},
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=10,
        )
        if not response.ok:
            return []
        return _parse_rss_items(response.text, 'Yahoo Finance RSS', limit=5)
    except Exception as exc:
        logger.warning('Yahoo RSS fetch failed for %s: %s', symbol, exc)
        return []


def fetch_news_items(symbol: str) -> list[dict[str, str]]:
    google = fetch_google_news(symbol)
    yahoo_json = fetch_yahoo_finance_news(symbol)
    yahoo_rss = fetch_yahoo_rss(symbol)

    # Merge, deduplicate by title (case-insensitive first 60 chars)
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for item in google + yahoo_json + yahoo_rss:
        key = item['title'][:60].lower()
        if key not in seen:
            seen.add(key)
            merged.append(item)

    if not merged:
        raise HTTPException(status_code=502, detail='Aucune source de news disponible pour ce symbole.')

    return merged[:10]


# Weighted lexicons — stronger words contribute more, mild ones less.
POSITIVE_WEIGHTS: dict[str, float] = {
    # EN — strong
    'crash higher': 2.5, 'soars': 2.2, 'soar': 2.2, 'skyrocket': 2.5, 'skyrockets': 2.5,
    'surge': 2.0, 'surges': 2.0, 'surging': 2.0, 'breakout': 1.8, 'breakthrough': 1.8,
    'record high': 2.2, 'record': 1.5, 'rally': 1.6, 'rallies': 1.6, 'rebound': 1.4,
    'beat': 1.6, 'beats': 1.6, 'upgrade': 1.6, 'upgrades': 1.6, 'upgraded': 1.6,
    'outperform': 1.5, 'outperforms': 1.5, 'bullish': 1.7, 'bull': 1.0,
    # EN — mild
    'growth': 1.0, 'gain': 0.9, 'gains': 0.9, 'rise': 0.8, 'rises': 0.8, 'rising': 0.8,
    'positive': 0.9, 'strong': 1.0, 'expansion': 1.0, 'profit': 1.0, 'profits': 1.0,
    'optimism': 1.1, 'optimistic': 1.1, 'momentum': 0.9, 'boost': 1.2, 'boosts': 1.2,
    'jump': 1.4, 'jumps': 1.4, 'climb': 1.0, 'climbs': 1.0, 'higher': 0.7,
    # FR — strong
    'envolée': 2.2, 'envolee': 2.2, 'flambée': 2.2, 'flambee': 2.2, 'envole': 2.0,
    'bondit': 1.8, 'bondissent': 1.8, 'explose': 2.0, 'explosent': 2.0,
    'record historique': 2.2, 'plus haut': 1.6, 'au plus haut': 1.8,
    'révision à la hausse': 2.0, 'revision a la hausse': 2.0, 'relèvement': 1.6, 'relevement': 1.6,
    'surperforme': 1.5, 'surperformance': 1.5, 'dépasse les attentes': 2.0,
    'dépasse': 1.4, 'depasse': 1.4, 'rebond': 1.4,
    # FR — mild
    'hausse': 1.0, 'progression': 1.0, 'progresse': 1.0, 'croissance': 1.0,
    'solide': 1.0, 'positif': 0.9, 'bénéfice': 1.0, 'benefice': 1.0,
    'optimisme': 1.1, 'fort': 0.8, 'gagne': 0.9, 'monte': 0.9, 'supérieur': 0.9,
    'redresse': 1.2, 'redressement': 1.2, 'attractif': 1.0,
}

NEGATIVE_WEIGHTS: dict[str, float] = {
    # EN — strong
    'crash': 2.5, 'collapse': 2.5, 'collapses': 2.5, 'plunge': 2.2, 'plunges': 2.2,
    'plunging': 2.2, 'tumble': 1.8, 'tumbles': 1.8, 'slump': 1.8, 'slumps': 1.8,
    'rout': 2.0, 'meltdown': 2.5, 'crisis': 2.0, 'recession': 2.2, 'bankruptcy': 2.5,
    'downgrade': 1.7, 'downgrades': 1.7, 'downgraded': 1.7, 'miss': 1.6, 'misses': 1.6,
    'warning': 1.6, 'warns': 1.6, 'bearish': 1.7, 'bear market': 2.0,
    'underperform': 1.5, 'underperforms': 1.5, 'sell-off': 2.0, 'selloff': 2.0,
    'record low': 2.0,
    # EN — mild
    'fall': 1.0, 'falls': 1.0, 'falling': 1.0, 'drop': 1.0, 'drops': 1.0,
    'decline': 1.0, 'declines': 1.0, 'declining': 1.0, 'cut': 1.2, 'cuts': 1.2,
    'loss': 1.0, 'losses': 1.0, 'negative': 0.9, 'weak': 1.0, 'weakness': 1.0,
    'risk': 0.8, 'risks': 0.8, 'concern': 0.9, 'concerns': 0.9, 'pressure': 0.8,
    'fears': 1.1, 'fear': 1.0, 'lower': 0.7, 'slowdown': 1.4,
    # FR — strong
    'effondre': 2.5, 'effondrement': 2.5, 's effondre': 2.5, 'krach': 2.5,
    'plonge': 2.0, 'plongent': 2.0, 'chute': 1.8, 'chutent': 1.8, 'dégringole': 2.0,
    'degringole': 2.0, 'panique': 2.0, 'crise': 2.0, 'récession': 2.2, 'recession': 2.2,
    'révision à la baisse': 2.0, 'revision a la baisse': 2.0, 'dégradation': 1.6, 'degradation': 1.6,
    'avertissement': 1.6, 'profit warning': 2.0, 'au plus bas': 1.8, 'plus bas': 1.5,
    # FR — mild
    'baisse': 1.0, 'baissent': 1.0, 'recul': 1.1, 'recule': 1.1, 'reculent': 1.1,
    'risque': 0.8, 'risques': 0.8, 'perte': 1.0, 'pertes': 1.0, 'négatif': 0.9,
    'faible': 0.9, 'faiblesse': 1.0, 'déclin': 1.1, 'declin': 1.1,
    'déception': 1.5, 'deception': 1.5, 'inférieur': 0.9, 'inferieur': 0.9,
    'inquiétude': 1.2, 'inquietude': 1.2, 'crainte': 1.2, 'craintes': 1.2,
    'cède': 1.0, 'cede': 1.0, 'mauvais': 0.9, 'difficile': 0.7, 'ralentissement': 1.3,
}


def _score_headline(title: str) -> tuple[float, float, list[str], list[str]]:
    """Returns (positive_weight, negative_weight, matched_pos, matched_neg)."""
    normalized = ' ' + title.lower() + ' '
    pos_hits: list[tuple[str, float]] = []
    neg_hits: list[tuple[str, float]] = []
    for kw, w in POSITIVE_WEIGHTS.items():
        if kw in normalized:
            pos_hits.append((kw, w))
    for kw, w in NEGATIVE_WEIGHTS.items():
        if kw in normalized:
            neg_hits.append((kw, w))
    # Keep only the strongest hit per side to avoid double-counting synonyms like "fall/falls"
    pos_w = max((w for _, w in pos_hits), default=0.0)
    neg_w = max((w for _, w in neg_hits), default=0.0)
    return pos_w, neg_w, [k for k, _ in pos_hits], [k for k, _ in neg_hits]


def heuristic_news_analysis(symbol: str, items: list[dict[str, str]]) -> dict[str, Any]:
    """
    News sentiment built from weighted keyword matches with:
      - per-headline strongest-hit selection (avoids stacking synonyms)
      - recency decay (newest headline weighs ~1.0, oldest ~0.55)
      - tanh saturation so scores spread across the full [-1, 1] range
    """
    candidates = items[:8]
    if not candidates:
        return {
            'sentiment': 0.0,
            'confidence': 38,
            'summary': f'Aucune news exploitable pour {symbol}.',
            'drivers': ['Pas de headlines disponibles dans les sources surveillées.'],
            'llmUsed': False,
            'model': 'heuristic-fallback',
        }

    raw_score = 0.0
    hit_count = 0
    drivers: list[tuple[float, str]] = []  # (abs_weight, sentence)
    n = len(candidates)

    for i, item in enumerate(candidates):
        recency = 1.0 - (i / max(n, 1)) * 0.45  # 1.00 → 0.55
        pos_w, neg_w, pos_kws, neg_kws = _score_headline(item['title'])
        net = pos_w - neg_w
        if pos_w > 0 or neg_w > 0:
            hit_count += 1
            raw_score += net * recency
            if net > 0:
                lex = ', '.join(pos_kws[:2])
                drivers.append((abs(net), f"Headline haussière ({lex}) : {item['title']}"))
            elif net < 0:
                lex = ', '.join(neg_kws[:2])
                drivers.append((abs(net), f"Headline baissière ({lex}) : {item['title']}"))

    # tanh saturation gives a smooth, dynamic spread:
    #   raw=±0.5 → ~±0.24   raw=±1 → ~±0.46   raw=±2 → ~±0.76   raw=±3.5 → ~±0.93
    sentiment = math.tanh(raw_score / 2.2)
    sentiment = round(clamp(sentiment, -1.0, 1.0), 3)

    # Confidence: more matched headlines + bigger raw magnitude → higher confidence
    coverage_boost = min(hit_count, 6) * 6.0
    magnitude_boost = min(abs(raw_score), 5.0) * 5.0
    confidence = int(clamp(40 + coverage_boost + magnitude_boost, 40, 88))

    if sentiment > 0.35:
        bias = 'nettement haussier'
    elif sentiment > 0.12:
        bias = 'légèrement haussier'
    elif sentiment < -0.35:
        bias = 'nettement baissier'
    elif sentiment < -0.12:
        bias = 'légèrement baissier'
    else:
        bias = 'neutre'

    drivers.sort(key=lambda d: d[0], reverse=True)
    top_drivers = [text for _, text in drivers[:3]] or [
        'Peu de signaux textuels forts dans les headlines récentes — sentiment neutre par défaut.'
    ]

    return {
        'sentiment': sentiment,
        'confidence': confidence,
        'summary': f"Lecture news pour {symbol} : flux {bias} ({hit_count}/{n} headlines marquées, intensité {raw_score:+.2f}).",
        'drivers': top_drivers,
        'llmUsed': False,
        'model': 'heuristic-fallback',
    }


def extract_json_object(content: str) -> dict[str, Any] | None:
    """Robust JSON extraction: strips markdown fences, balances brackets, tolerates truncation."""
    if not content:
        return None

    # Strip markdown code fences
    cleaned = re.sub(r'```(?:json)?\s*', '', content)
    cleaned = cleaned.replace('```', '')

    # Find first '{'
    start = cleaned.find('{')
    if start < 0:
        return None

    # Walk forward, tracking bracket depth, respecting strings
    depth = 0
    in_str = False
    escape = False
    end = -1
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    candidates: list[str] = []
    if end > 0:
        candidates.append(cleaned[start:end + 1])
    # Truncation rescue: re-balance missing braces / close open string
    snippet = cleaned[start:]
    if depth > 0:
        repaired = snippet
        if in_str:
            repaired += '"'
        repaired += '}' * depth
        candidates.append(repaired)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    return None


def request_openrouter_analysis(symbol: str, items: list[dict[str, str]]) -> dict[str, Any]:
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        logger.info('OPENROUTER_API_KEY absent, utilisation de l heuristique pour %s', symbol)
        return heuristic_news_analysis(symbol, items)
    if not items:
        return heuristic_news_analysis(symbol, items)

    headlines_block = '\n'.join(
        f"{i+1}. [{item['source']}] {item['title']}"
        for i, item in enumerate(items[:8])
    )
    payload = {
        'model': OPENROUTER_MODEL,
        'temperature': 0.25,
        'max_tokens': 4000,
        # Disable Gemini 3.x "thinking" tokens — otherwise they eat the whole budget
        'reasoning': {'enabled': False, 'max_tokens': 0},
        'messages': [
            {
                'role': 'system',
                'content': (
                    "Tu es un analyste buy-side senior. Tu lis des titres de presse récents sur un actif financier "
                    "et tu produis un score de sentiment de marché à court terme.\n\n"
                    "RÈGLES DE CALIBRATION OBLIGATOIRES — utilise TOUTE l'échelle [-1.0, 1.0] :\n"
                    "  • +0.85 à +1.00  → catalyseur majeur très haussier (résultats record, rachat, percée historique)\n"
                    "  • +0.55 à +0.84  → flux clairement positif (upgrades, beats EPS, momentum confirmé)\n"
                    "  • +0.25 à +0.54  → flux modérément positif (newsflow constructif, perspectives bien orientées)\n"
                    "  • +0.05 à +0.24  → biais légèrement positif (signaux faibles)\n"
                    "  • -0.04 à +0.04  → vraiment neutre (rare : seulement si headlines sans implication directionnelle)\n"
                    "  • -0.24 à -0.05  → biais légèrement négatif\n"
                    "  • -0.54 à -0.25  → flux modérément négatif (downgrades, miss, ralentissement)\n"
                    "  • -0.84 à -0.55  → flux clairement négatif (warnings, déceptions multiples)\n"
                    "  • -1.00 à -0.85  → choc baissier majeur (crash, scandale, faillite, krach sectoriel)\n\n"
                    "Tu DOIS varier ta réponse selon les headlines — ne réponds JAMAIS 0.2 par défaut.\n"
                    "Pondère par la fraîcheur (premiers titres = plus récents = plus de poids) et la matérialité.\n\n"
                    "Format de sortie : JSON STRICT, sans markdown, sans commentaire, avec exactement ces clés :\n"
                    "  sentiment   : float, échelle ci-dessus\n"
                    "  confidence  : int dans [40, 95] — plus haut si signaux convergents et nombreux\n"
                    "  summary     : string en français, 1 phrase concise et opérationnelle (pas générique)\n"
                    "  drivers     : array de 2 à 3 strings en français — chaque driver cite explicitement un fait du headline"
                ),
            },
            {
                'role': 'user',
                'content': (
                    f"Actif analysé : {symbol}\n\n"
                    f"Headlines récentes (du plus récent au plus ancien) :\n{headlines_block}\n\n"
                    "Évalue le sentiment selon la grille de calibration. "
                    "Choisis une valeur PRÉCISE (ex : -0.43, +0.62) — pas un nombre rond comme 0.2 ou 0.5. "
                    "Retourne uniquement le JSON."
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
                'HTTP-Referer': 'http://localhost:8787',
                'X-Title': 'bot_trading',
            },
            json=payload,
            timeout=35,
        )
        if not response.ok:
            logger.error('OpenRouter %s pour %s : %s', response.status_code, symbol, response.text[:500])
            response.raise_for_status()
        raw_content = response.json()['choices'][0]['message']['content']
        content = raw_content if isinstance(raw_content, str) else json.dumps(raw_content)
        parsed = extract_json_object(content)
        if not parsed:
            logger.warning(
                'OpenRouter JSON non parseable pour %s (len=%d, finish=%s) : %r',
                symbol, len(content), response.json()['choices'][0].get('finish_reason'), content,
            )
            raise ValueError('JSON parsing failed')

        sentiment = clamp(float(parsed.get('sentiment', 0.0)), -1.0, 1.0)
        confidence = int(clamp(float(parsed.get('confidence', 55)), 0, 100))
        summary = str(parsed.get('summary', 'Signal news disponible.'))
        drivers = parsed.get('drivers', [])
        if not isinstance(drivers, list):
            drivers = [str(drivers)]

        logger.info('OpenRouter OK pour %s : sentiment=%.2f confidence=%d', symbol, sentiment, confidence)
        return {
            'sentiment': sentiment,
            'confidence': confidence,
            'summary': summary,
            'drivers': [str(d) for d in drivers[:3]],
            'llmUsed': True,
            'model': OPENROUTER_MODEL,
        }
    except Exception as exc:
        logger.error('OpenRouter failed pour %s : %s', symbol, exc)
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