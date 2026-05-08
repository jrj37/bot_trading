import { startTransition, useDeferredValue, useEffect, useState } from 'react';

import { MarketChart } from './components/MarketChart';
import type { MarketResponse, NewsItem, NewsResponse, SignalResponse } from './types';

const presets = [
  { label: 'S&P 500', symbol: 'SXR8.DE' },
  { label: 'Emerging Markets', symbol: 'IS3N.DE' },
  { label: 'Stoxx Europe 600', symbol: 'EXSA.DE' },
] as const;
const defaultSymbol = presets[0].symbol;
const ranges = [
  { label: '1M', value: '1mo' },
  { label: '3M', value: '3mo' },
  { label: '6M', value: '6mo' },
  { label: '1Y', value: '1y' },
] as const;

async function fetchJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.message ?? 'Erreur reseau.');
  }

  return payload as T;
}

function formatPrice(value: number, currency: string) {
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency,
    maximumFractionDigits: currency === 'USD' ? 2 : 0,
  }).format(value);
}

function formatCompact(value: number) {
  return new Intl.NumberFormat('fr-FR', {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value);
}

function signalTone(action?: SignalResponse['action']) {
  if (action === 'buy') {
    return 'signal-tone--buy';
  }

  if (action === 'sell') {
    return 'signal-tone--sell';
  }

  return 'signal-tone--hold';
}

function signalBadgeClass(action?: SignalResponse['action']) {
  if (action === 'buy') {
    return 'signal-badge signal-badge--buy';
  }

  if (action === 'sell') {
    return 'signal-badge signal-badge--sell';
  }

  return 'signal-badge signal-badge--hold';
}

function sparklinePath(values: number[]) {
  if (values.length === 0) {
    return '';
  }

  const width = 320;
  const height = 70;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;

  return values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / spread) * height;
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
}

function RangeMeter({ low, high, current }: { low: number; high: number; current: number }) {
  const position = high === low ? 50 : ((current - low) / (high - low)) * 100;

  return (
    <div className="range-meter">
      <div className="range-meter__labels">
        <span>{low.toFixed(2)}</span>
        <span>{high.toFixed(2)}</span>
      </div>
      <div className="range-meter__track">
        <span className="range-meter__fill" style={{ width: `${Math.min(Math.max(position, 0), 100)}%` }} />
      </div>
    </div>
  );
}

function NewsRail({ items }: { items: NewsItem[] }) {
  return (
    <div className="news-rail">
      <span className="news-rail__label">Events</span>
      <div className="news-rail__dots">
        {items.map((item, index) => (
          <div className="news-rail__item" key={`${item.link}-${index}`} title={item.title}>
            <span className={`news-rail__dot news-rail__dot--${index % 4}`} />
            <small>{new Date(item.published).toLocaleDateString('fr-FR')}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const [draftSymbol, setDraftSymbol] = useState(defaultSymbol);
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [range, setRange] = useState<(typeof ranges)[number]['value']>('1y');
  const [market, setMarket] = useState<MarketResponse | null>(null);
  const [news, setNews] = useState<NewsResponse | null>(null);
  const [signal, setSignal] = useState<SignalResponse | null>(null);
  const [ranking, setRanking] = useState<Array<SignalResponse & { labelName: string }>>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const deferredSymbol = useDeferredValue(symbol);

  useEffect(() => {
    const controller = new AbortController();

    startTransition(() => {
      setIsLoading(true);
      setError(null);
    });

    Promise.all([
      fetchJson<MarketResponse>(`/api/market?symbol=${encodeURIComponent(deferredSymbol)}&range=${range}`, controller.signal),
      fetchJson<NewsResponse>(`/api/news?symbol=${encodeURIComponent(deferredSymbol)}`, controller.signal),
      fetchJson<SignalResponse>(`/api/signal?symbol=${encodeURIComponent(deferredSymbol)}&range=${range}`, controller.signal),
      Promise.all(
        presets.map(async (preset) => {
          const presetSignal = await fetchJson<SignalResponse>(
            `/api/signal?symbol=${encodeURIComponent(preset.symbol)}&range=${range}`,
            controller.signal,
          );

          return {
            ...presetSignal,
            labelName: preset.label,
          };
        }),
      ),
    ])
      .then(([marketPayload, newsPayload, signalPayload, rankingPayload]) => {
        setMarket(marketPayload);
        setNews(newsPayload);
        setSignal(signalPayload);
        setRanking(
          rankingPayload.sort((left, right) => {
            if (right.action === left.action) {
              return right.confidence - left.confidence;
            }

            const order = { buy: 3, hold: 2, sell: 1 };
            return order[right.action] - order[left.action];
          }),
        );
      })
      .catch((requestError: Error) => {
        if (requestError.name === 'AbortError') {
          return;
        }

        setError(requestError.message);
      })
      .finally(() => {
        setIsLoading(false);
      });

    return () => controller.abort();
  }, [deferredSymbol, range]);

  const points = market?.points ?? [];
  const closingSeries = points.slice(-80).map((point) => point.close);
  const latestClose = market?.stats.latestClose ?? 0;
  const changePercent = market?.stats.changePercent ?? 0;
  const isPositive = changePercent >= 0;

  return (
    <main className="dashboard-shell">
      <div className="dashboard-backdrop" />
      <section className="hero-card">
        <div className="hero-card__intro">
          <p className="eyebrow">Ticker Room</p>
          <div className="hero-card__controls">
            <form
              className="ticker-form"
              onSubmit={(event) => {
                event.preventDefault();
                startTransition(() => {
                  setSymbol(draftSymbol.trim().toUpperCase() || defaultSymbol);
                });
              }}
            >
              <label htmlFor="symbol" className="sr-only">
                Symbole de marche
              </label>
              <input
                id="symbol"
                value={draftSymbol}
                onChange={(event) => setDraftSymbol(event.target.value)}
                placeholder="Ex: SXR8.DE, IS3N.DE, EXSA.DE"
              />
              <button type="submit">Charger</button>
            </form>
            <div className="preset-strip">
              {presets.map((preset) => (
                <button
                  key={preset.symbol}
                  className={preset.symbol === symbol ? 'active' : ''}
                  onClick={() => {
                    setDraftSymbol(preset.symbol);
                    startTransition(() => setSymbol(preset.symbol));
                  }}
                  title={preset.symbol}
                  type="button"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="hero-card__headline">
          <div>
            <p className="eyebrow">Marche suivi</p>
            <h1>
              {market?.symbol ?? symbol}
              <span>{market?.exchangeName ?? 'Loading market'}</span>
            </h1>
          </div>
          <div className="headline-stats">
            <article>
              <span>Close</span>
              <strong>{market ? formatPrice(latestClose, market.currency) : '--'}</strong>
            </article>
            <article>
              <span>50 day moving avg</span>
              <strong>{market ? formatPrice(market.stats.movingAverage50, market.currency) : '--'}</strong>
            </article>
            <article>
              <span>Signal</span>
              <strong className={signalTone(signal?.action)}>{signal?.label ?? '--'}</strong>
            </article>
            <article>
              <span>Confiance</span>
              <strong className={signalTone(signal?.action)}>{signal ? `${signal.confidence}/100` : '--'}</strong>
            </article>
            <article>
              <span>52 week range</span>
              <strong>
                {market ? `${market.stats.low52w.toFixed(2)} - ${market.stats.high52w.toFixed(2)}` : '--'}
              </strong>
            </article>
          </div>
        </div>
      </section>

      {error ? <div className="status-banner status-banner--error">{error}</div> : null}
      {isLoading ? <div className="status-banner">Chargement des donnees en cours...</div> : null}

      <section className="dashboard-grid">
        <article className="panel panel--chart">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Prix</p>
              <h2>Lecture graphique orientee decision</h2>
            </div>
            <div className="range-switcher">
              {ranges.map((rangeOption) => (
                <button
                  key={rangeOption.value}
                  className={rangeOption.value === range ? 'active' : ''}
                  onClick={() => setRange(rangeOption.value)}
                  type="button"
                >
                  {rangeOption.label}
                </button>
              ))}
            </div>
          </div>

          {market ? <MarketChart points={market.points} /> : <div className="chart-placeholder" />}
          <NewsRail items={news?.items.slice(0, 6) ?? []} />
          <div className="mini-trend">
            <svg viewBox="0 0 320 70" preserveAspectRatio="none">
              <path d={sparklinePath(closingSeries)} />
            </svg>
          </div>
        </article>

        <aside className="panel panel--summary">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Signal</p>
              <h2>Lecture rapide</h2>
            </div>
            <div className={signalBadgeClass(signal?.action)}>
              {signal?.label ?? `${changePercent.toFixed(2)}%`}
            </div>
          </div>

          <div className="stat-grid">
            <article>
              <span>Dernier prix</span>
              <strong>{market ? formatPrice(market.stats.latestClose, market.currency) : '--'}</strong>
            </article>
            <article>
              <span>Variation</span>
              <strong className={isPositive ? 'positive' : 'negative'}>{changePercent.toFixed(2)}%</strong>
            </article>
            <article>
              <span>RSI 14j</span>
              <strong>{market ? market.stats.rsi14.toFixed(1) : '--'}</strong>
            </article>
            <article>
              <span>Indice buy/sell</span>
              <strong className={signalTone(signal?.action)}>{signal ? `${signal.confidence}/100` : '--'}</strong>
            </article>
            <article>
              <span>Score technique</span>
              <strong className={signalTone(signal?.action)}>{signal ? signal.technicalScore.toFixed(2) : '--'}</strong>
            </article>
            <article>
              <span>Score news</span>
              <strong className={signalTone(signal?.action)}>{signal ? signal.newsScore.toFixed(2) : '--'}</strong>
            </article>
          </div>

          <div className="summary-copy">
            <p className="eyebrow">Decision engine</p>
            <div>
              {signal?.summary ? (
                signal.summary.split('\n').map((line, index) => <p key={`${line}-${index}`}>{line}</p>)
              ) : (
                <p>
                  Le moteur de decision combine tendance, momentum, RSI, volumes et lecture des news pour
                  produire un signal achat, conservation ou vente.
                </p>
              )}
            </div>
          </div>

          <div className="summary-copy">
            <p className="eyebrow">Moteur news</p>
            <div>
              <p>{signal?.llmUsed ? `LLM OpenRouter: ${signal.model}` : 'Fallback heuristique sur les headlines'}</p>
              {(signal?.newsDrivers ?? []).map((line, index) => <p key={`${line}-${index}`}>{line}</p>)}
            </div>
          </div>

          <div className="summary-copy">
            <p className="eyebrow">Moteur technique</p>
            <div>
              {(signal?.technicalDrivers ?? []).map((line, index) => <p key={`${line}-${index}`}>{line}</p>)}
              {!signal?.technicalDrivers?.length ? <p>En attente des signaux techniques.</p> : null}
            </div>
          </div>

          {market ? (
            <div className="summary-range">
              <p className="eyebrow">52 week range</p>
              <RangeMeter
                low={market.stats.low52w}
                high={market.stats.high52w}
                current={market.stats.latestClose}
              />
            </div>
          ) : null}
        </aside>
      </section>

      <section className="dashboard-grid dashboard-grid--bottom">
        <article className="panel panel--ranking">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Classement</p>
              <h2>Ou acheter en premier</h2>
            </div>
          </div>
          <div className="ranking-list">
            {ranking.map((entry, index) => (
              <button
                key={entry.symbol}
                className="ranking-card"
                onClick={() => {
                  setDraftSymbol(entry.symbol);
                  startTransition(() => setSymbol(entry.symbol));
                }}
                type="button"
              >
                <div className="ranking-card__rank">{String(index + 1).padStart(2, '0')}</div>
                <div className="ranking-card__body">
                  <div className="ranking-card__topline">
                    <strong>{entry.labelName}</strong>
                    <span>{entry.symbol}</span>
                  </div>
                  <p>{entry.summary}</p>
                  <div className="ranking-card__metrics">
                    <span className={signalBadgeClass(entry.action)}>{entry.label}</span>
                    <span className={signalTone(entry.action)}>Confiance {entry.confidence}/100</span>
                    <span>Score {entry.score.toFixed(2)}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </article>

        <article className="panel panel--news-list">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Actualites</p>
              <h2>Flux editorial</h2>
            </div>
          </div>
          <div className="headline-list">
            {(news?.items ?? []).slice(0, 6).map((item, index) => (
              <a className="headline-item" href={item.link} key={`${item.link}-${index}`} rel="noreferrer" target="_blank">
                <span>{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <strong>{item.title}</strong>
                  <small>
                    {item.source} | {new Date(item.published).toLocaleDateString('fr-FR')}
                  </small>
                </div>
              </a>
            ))}
          </div>
        </article>

        <article className="panel panel--note">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Build note</p>
              <h2>Nouvelle base projet</h2>
            </div>
          </div>
          <p>
            Le dashboard tourne maintenant avec un frontend React/Vite et un backend Python FastAPI. Le score
            de confiance combine signaux techniques et lecture des news, avec OpenRouter quand une cle API est
            disponible.
          </p>
          <ul className="plain-list">
            <li>Frontend: React + Vite + TypeScript</li>
            <li>Graphiques: Lightweight Charts</li>
            <li>Backend: FastAPI Python</li>
          </ul>
        </article>
      </section>
    </main>
  );
}
