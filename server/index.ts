import path from 'node:path';
import { fileURLToPath } from 'node:url';

import cors from 'cors';
import dotenv from 'dotenv';
import express from 'express';
import { XMLParser } from 'fast-xml-parser';

dotenv.config();

const app = express();
const PORT = Number(process.env.PORT ?? 8787);
const parser = new XMLParser({ ignoreAttributes: false });
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const distPath = path.resolve(__dirname, '../dist');

app.use(cors());
app.use(express.json());

interface MarketPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface MarketStats {
  latestClose: number;
  changePercent: number;
  movingAverage50: number;
  high52w: number;
  low52w: number;
  averageVolume20: number;
}

interface NewsItem {
  title: string;
  link: string;
  source: string;
  published: string;
}

function xmlValueToText(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }

  if (value && typeof value === 'object' && '#text' in value) {
    const textValue = (value as { '#text'?: unknown })['#text'];
    return typeof textValue === 'string' ? textValue : '';
  }

  return '';
}

function normalizeSymbol(input: string): string {
  return input.trim().toUpperCase() || 'SXR8.DE';
}

function buildNewsQuery(symbol: string): string {
  if (symbol === 'SXR8.DE') {
    return 'S&P 500 stock market';
  }

  if (symbol === 'IS3N.DE') {
    return 'MSCI Emerging Markets stock market';
  }

  if (symbol === 'EXSA.DE') {
    return 'STOXX Europe 600 stock market';
  }

  if (symbol === 'BTC-USD') {
    return 'BTC OR Bitcoin crypto market';
  }

  if (symbol === 'ETH-USD') {
    return 'ETH OR Ethereum crypto market';
  }

  if (symbol === '^GSPC') {
    return 'S&P 500 stock market';
  }

  return `${symbol} stock market finance`;
}

function average(values: number[]): number {
  if (values.length === 0) {
    return 0;
  }

  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function computeMarketStats(points: MarketPoint[]): MarketStats {
  const closes = points.map((point) => point.close);
  const volumes = points.map((point) => point.volume).filter((volume) => volume > 0);
  const latestClose = closes.at(-1) ?? 0;
  const baseClose = closes[0] ?? latestClose;
  const movingAverageWindow = closes.slice(-50);
  const latestTwentyVolumes = volumes.slice(-20);

  return {
    latestClose,
    changePercent: baseClose === 0 ? 0 : ((latestClose - baseClose) / baseClose) * 100,
    movingAverage50: average(movingAverageWindow),
    high52w: Math.max(...closes),
    low52w: Math.min(...closes),
    averageVolume20: average(latestTwentyVolumes),
  };
}

async function fetchMarketData(symbol: string, range: string, interval: string) {
  const url = new URL(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}`);
  url.searchParams.set('range', range);
  url.searchParams.set('interval', interval);
  url.searchParams.set('includePrePost', 'false');
  url.searchParams.set('events', 'div,splits');

  const response = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0',
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Yahoo Finance a repondu ${response.status}.`);
  }

  const payload = await response.json() as {
    chart?: {
      result?: Array<{
        meta?: {
          currency?: string;
          exchangeName?: string;
          regularMarketPrice?: number;
        };
        timestamp?: number[];
        indicators?: {
          quote?: Array<{
            open?: Array<number | null>;
            high?: Array<number | null>;
            low?: Array<number | null>;
            close?: Array<number | null>;
            volume?: Array<number | null>;
          }>;
        };
      }>;
      error?: {
        description?: string;
      } | null;
    };
  };

  const result = payload.chart?.result?.[0];
  if (!result || !result.timestamp || !result.indicators?.quote?.[0]) {
    const message = payload.chart?.error?.description ?? 'Flux de marche indisponible pour ce symbole.';
    throw new Error(message);
  }

  const quote = result.indicators.quote[0];
  const points: MarketPoint[] = result.timestamp
    .map((timestamp, index) => {
      const open = quote.open?.[index];
      const high = quote.high?.[index];
      const low = quote.low?.[index];
      const close = quote.close?.[index];
      const volume = quote.volume?.[index] ?? 0;

      if (
        open == null ||
        high == null ||
        low == null ||
        close == null ||
        Number.isNaN(open) ||
        Number.isNaN(high) ||
        Number.isNaN(low) ||
        Number.isNaN(close)
      ) {
        return null;
      }

      return {
        time: new Date(timestamp * 1000).toISOString().slice(0, 10),
        open,
        high,
        low,
        close,
        volume,
      };
    })
    .filter((point): point is MarketPoint => point !== null);

  if (points.length === 0) {
    throw new Error('Aucune bougie exploitable retournee par Yahoo Finance.');
  }

  return {
    symbol,
    currency: result.meta?.currency ?? 'USD',
    exchangeName: result.meta?.exchangeName ?? 'Market',
    regularMarketPrice: result.meta?.regularMarketPrice ?? points.at(-1)?.close ?? 0,
    points,
    stats: computeMarketStats(points),
  };
}

async function fetchNewsItems(symbol: string): Promise<NewsItem[]> {
  const query = buildNewsQuery(symbol);
  const url = new URL('https://news.google.com/rss/search');
  url.searchParams.set('q', query);
  url.searchParams.set('hl', 'fr');
  url.searchParams.set('gl', 'FR');
  url.searchParams.set('ceid', 'FR:fr');

  const response = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0',
      Accept: 'application/rss+xml, application/xml;q=0.9, */*;q=0.8',
    },
  });

  if (!response.ok) {
    throw new Error(`Google News a repondu ${response.status}.`);
  }

  const xml = await response.text();
  const parsed = parser.parse(xml) as {
    rss?: {
      channel?: {
        item?: Array<{
          title?: string;
          link?: string;
          source?: string;
          pubDate?: string;
        }> | {
          title?: string;
          link?: string;
          source?: string;
          pubDate?: string;
        };
      };
    };
  };

  const rawItems = parsed.rss?.channel?.item;
  const items = Array.isArray(rawItems) ? rawItems : rawItems ? [rawItems] : [];

  return items.slice(0, 8).map((item) => ({
    title: (xmlValueToText(item.title) || 'Sans titre').replace(' - Google News', ''),
    link: xmlValueToText(item.link) || '#',
    source: xmlValueToText(item.source) || 'Google News',
    published: xmlValueToText(item.pubDate) || 'Date inconnue',
  }));
}

function buildNewsSummary(symbol: string, items: NewsItem[]): string | null {
  if (items.length === 0) {
    return null;
  }

  const bulletPoints = items
    .slice(0, 3)
    .map((item) => `- ${item.title}`);
  const latestSource = items[0]?.source ?? 'Google News';

  return [
    `Synthese rapide pour ${symbol} :`,
    ...bulletPoints,
    `Impact potentiel: sentiment de marche a confirmer avec les prix et volumes. Source dominante: ${latestSource}.`,
  ].join('\n');
}

app.get('/api/health', (_request, response) => {
  response.json({ ok: true });
});

app.get('/api/market', async (request, response) => {
  try {
    const symbol = normalizeSymbol(String(request.query.symbol ?? 'SXR8.DE'));
    const range = String(request.query.range ?? '1y');
    const interval = String(request.query.interval ?? '1d');
    const market = await fetchMarketData(symbol, range, interval);

    response.json(market);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Erreur inconnue sur le flux marche.';
    response.status(502).json({ message });
  }
});

app.get('/api/news', async (request, response) => {
  try {
    const symbol = normalizeSymbol(String(request.query.symbol ?? 'SXR8.DE'));
    const items = await fetchNewsItems(symbol);
    const summary = buildNewsSummary(symbol, items);

    response.json({
      symbol,
      source: 'Google News',
      summary,
      items,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Erreur inconnue sur le flux news.';
    response.status(502).json({ message });
  }
});

app.use(express.static(distPath));
app.use((request, response, next) => {
  if (request.method !== 'GET' || request.path.startsWith('/api')) {
    next();
    return;
  }

  response.sendFile(path.join(distPath, 'index.html'), (error) => {
    if (error) {
      next();
    }
  });
});

app.listen(PORT, () => {
  console.log(`Server listening on http://localhost:${PORT}`);
});
