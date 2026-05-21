import { startTransition, useDeferredValue, useEffect, useRef, useState } from 'react';

import { MarketChart } from './components/MarketChart';
import type { MarketResponse, NewsItem, NewsResponse, SignalResponse } from './types';

const presets = [
  { label: 'S&P 500', symbol: 'SXR8.DE', category: 'ETF', origin: 'Étrangère' },
  { label: 'Emerging Markets', symbol: 'IS3N.DE', category: 'ETF', origin: 'Étrangère' },
  { label: 'Stoxx Europe 600', symbol: 'EXSA.DE', category: 'ETF', origin: 'Étrangère' },
  { label: 'Nvidia', symbol: 'NVDA', category: 'Action', origin: 'Étrangère' },
  { label: 'Take-Two', symbol: 'TTWO', category: 'Action', origin: 'Étrangère' },
  { label: 'Crédit Agricole', symbol: 'ACA.PA', category: 'Action', origin: 'Française' },
] as const;

type Preset = (typeof presets)[number];
type RankingEntry = SignalResponse & { labelName: string; category: Preset['category']; origin: Preset['origin'] };

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
  if (!response.ok) throw new Error(payload.message ?? 'Erreur reseau.');
  return payload as T;
}

function formatPrice(value: number, currency: string) {
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency,
    maximumFractionDigits: currency === 'USD' ? 2 : 0,
  }).format(value);
}

function signalTone(action?: SignalResponse['action']) {
  if (action === 'buy') return 'signal-tone--buy';
  if (action === 'sell') return 'signal-tone--sell';
  return 'signal-tone--hold';
}

function signalBadgeClass(action?: SignalResponse['action']) {
  if (action === 'buy') return 'signal-badge signal-badge--buy';
  if (action === 'sell') return 'signal-badge signal-badge--sell';
  return 'signal-badge signal-badge--hold';
}

function sparklinePath(values: number[]) {
  if (values.length === 0) return '';
  const width = 320;
  const height = 60;
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

function Skeleton({ width = '5ch' }: { width?: string }) {
  return <span className="skeleton" style={{ minWidth: width }}>—</span>;
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

function FilterBar<T extends string>({
  options,
  value,
  onChange,
}: {
  options: T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="filter-bar">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          className={opt === value ? 'active' : ''}
          onClick={() => onChange(opt)}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

function Masthead({ isSyncing }: { isSyncing: boolean }) {
  return (
    <header className="masthead">
      <div className="masthead__brand">
        <span className="masthead__mark">Atelier<em>.</em></span>
        <span className="masthead__sub">Lecture de marché</span>
      </div>
      <span className={`masthead__live${isSyncing ? ' is-syncing' : ''}`}>
        {isSyncing ? 'Synchronisation' : 'Flux en direct'}
      </span>
    </header>
  );
}

export default function App() {
  const [view, setView] = useState<'dashboard' | 'ranking'>('dashboard');
  const [draftSymbol, setDraftSymbol] = useState<string>(defaultSymbol);
  const [symbol, setSymbol] = useState<string>(defaultSymbol);
  const [range, setRange] = useState<(typeof ranges)[number]['value']>('1y');
  const [market, setMarket] = useState<MarketResponse | null>(null);
  const [news, setNews] = useState<NewsResponse | null>(null);
  const [signal, setSignal] = useState<SignalResponse | null>(null);
  const [ranking, setRanking] = useState<RankingEntry[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterCategory, setFilterCategory] = useState<'Tous' | 'ETF' | 'Action'>('Tous');
  const [filterOrigin, setFilterOrigin] = useState<'Tous' | 'Française' | 'Étrangère'>('Tous');

  const deferredSymbol = useDeferredValue(symbol);
  const hasLoadedOnce = useRef(false);

  // Heavy fetch: market + news. Triggered only when symbol changes (always full year).
  useEffect(() => {
    const controller = new AbortController();
    setIsRefreshing(true);
    setError(null);

    Promise.all([
      fetchJson<MarketResponse>(`/api/market?symbol=${encodeURIComponent(deferredSymbol)}&range=1y`, controller.signal),
      fetchJson<NewsResponse>(`/api/news?symbol=${encodeURIComponent(deferredSymbol)}`, controller.signal),
    ])
      .then(([marketPayload, newsPayload]) => {
        startTransition(() => {
          setMarket(marketPayload);
          setNews(newsPayload);
        });
        hasLoadedOnce.current = true;
      })
      .catch((requestError: Error) => {
        if (requestError.name === 'AbortError') return;
        setError(requestError.message);
      })
      .finally(() => setIsRefreshing(false));

    return () => controller.abort();
  }, [deferredSymbol]);

  // Signal + ranking: depend on range. Refetched silently in the background.
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchJson<SignalResponse>(`/api/signal?symbol=${encodeURIComponent(deferredSymbol)}&range=${range}`, controller.signal),
      Promise.all(
        presets.map(async (preset) => {
          const presetSignal = await fetchJson<SignalResponse>(
            `/api/signal?symbol=${encodeURIComponent(preset.symbol)}&range=${range}`,
            controller.signal,
          );
          return { ...presetSignal, labelName: preset.label, category: preset.category, origin: preset.origin };
        }),
      ),
    ])
      .then(([signalPayload, rankingPayload]) => {
        startTransition(() => {
          setSignal(signalPayload);
          setRanking(
            rankingPayload.sort((left, right) => {
              if (right.action === left.action) return right.confidence - left.confidence;
              const order = { buy: 3, hold: 2, sell: 1 };
              return order[right.action] - order[left.action];
            }),
          );
        });
      })
      .catch((requestError: Error) => {
        if (requestError.name === 'AbortError') return;
      });
    return () => controller.abort();
  }, [deferredSymbol, range]);

  // Client-side slice based on selected range — instant.
  const allPoints = market?.points ?? [];
  const points = (() => {
    if (allPoints.length === 0) return allPoints;
    const monthsByRange: Record<string, number> = { '1mo': 1, '3mo': 3, '6mo': 6, '1y': 12 };
    const months = monthsByRange[range] ?? 12;
    if (months >= 12) return allPoints;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - months);
    const cutoffTs = cutoff.getTime();
    return allPoints.filter((p) => new Date(p.time).getTime() >= cutoffTs);
  })();
  const closingSeries = points.slice(-80).map((point) => point.close);
  const latestClose = market?.stats.latestClose ?? 0;
  const changePercent = market?.stats.changePercent ?? 0;
  const isPositive = changePercent >= 0;
  const isInitialLoading = isRefreshing && !hasLoadedOnce.current;

  const filteredRanking = ranking.filter((entry) => {
    if (filterCategory !== 'Tous' && entry.category !== filterCategory) return false;
    if (filterOrigin !== 'Tous' && entry.origin !== filterOrigin) return false;
    return true;
  });

  function navigateTo(sym: string) {
    setDraftSymbol(sym);
    startTransition(() => setSymbol(sym));
    setView('dashboard');
  }

  if (view === 'ranking') {
    return (
      <main className="dashboard-shell">
        <Masthead isSyncing={isRefreshing} />

        <div className="ranking-page">
          <div className="ranking-page__header">
            <button className="back-btn" type="button" onClick={() => setView('dashboard')}>
              ← Tableau de bord
            </button>
            <div className="ranking-page__title">
              <p className="eyebrow">Classement</p>
              <h1>Où acheter en premier</h1>
            </div>
            <div className="ranking-page__filters">
              <div className="filter-group">
                <span className="filter-label">Type</span>
                <FilterBar
                  options={['Tous', 'ETF', 'Action'] as const}
                  value={filterCategory}
                  onChange={setFilterCategory}
                />
              </div>
              <div className="filter-group">
                <span className="filter-label">Origine</span>
                <FilterBar
                  options={['Tous', 'Française', 'Étrangère'] as const}
                  value={filterOrigin}
                  onChange={setFilterOrigin}
                />
              </div>
            </div>
          </div>

          <div className="ranking-list ranking-list--full">
            {filteredRanking.length === 0 && !isInitialLoading ? (
              <p className="ranking-empty">Aucun actif ne correspond aux filtres sélectionnés.</p>
            ) : (
              filteredRanking.map((entry, index) => (
                <button
                  key={entry.symbol}
                  className="ranking-card"
                  onClick={() => navigateTo(entry.symbol)}
                  type="button"
                >
                  <div className="ranking-card__rank">{String(index + 1).padStart(2, '0')}</div>
                  <div className="ranking-card__body">
                    <div className="ranking-card__topline">
                      <strong>{entry.labelName}</strong>
                      <div className="ranking-card__tags">
                        <span className="tag tag--category">{entry.category}</span>
                        <span className="tag tag--origin">{entry.origin}</span>
                        <span className="ranking-card__symbol">{entry.symbol}</span>
                      </div>
                    </div>
                    <p>{entry.summary}</p>
                    <div className="ranking-card__metrics">
                      <span className={signalBadgeClass(entry.action)}>{entry.label}</span>
                      <span className={signalTone(entry.action)}>Confiance {entry.confidence}/100</span>
                      <span>Score {entry.score.toFixed(2)}</span>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {error ? <div className="status-banner status-banner--error">{error}</div> : null}
      </main>
    );
  }

  return (
    <main className="dashboard-shell">
      <Masthead isSyncing={isRefreshing} />

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
                Symbole de marché
              </label>
              <input
                id="symbol"
                value={draftSymbol}
                onChange={(event) => setDraftSymbol(event.target.value)}
                placeholder="NVDA, ACA.PA, TTWO… ↵"
              />
            </form>
            <div className="preset-row">
              <span className="masthead__sub" style={{ color: 'var(--ivory-400)' }}>Sélection</span>
              <button className="ranking-btn" type="button" onClick={() => setView('ranking')}>
                Classement →
              </button>
            </div>
            <div className="preset-strip">
              {(['ETF', 'Action'] as const).map((cat) => (
                <div key={cat} className="preset-group">
                  <span className="preset-category">{cat}</span>
                  {presets
                    .filter((p) => p.category === cat)
                    .map((preset) => (
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
              ))}
            </div>
          </div>
        </div>

        <div className="hero-card__headline">
          <div>
            <p className="eyebrow">Marché suivi</p>
            <h1>
              {market?.symbol ?? symbol}
              <span>{market?.exchangeName ?? 'Marché global'}</span>
            </h1>
          </div>
          <div className="headline-stats">
            <article>
              <span>Close</span>
              <strong>
                {market ? formatPrice(latestClose, market.currency) : <Skeleton width="6ch" />}
              </strong>
            </article>
            <article>
              <span>Moy. mobile 50j</span>
              <strong>
                {market ? formatPrice(market.stats.movingAverage50, market.currency) : <Skeleton width="6ch" />}
              </strong>
            </article>
            <article>
              <span>Signal</span>
              <strong className={signalTone(signal?.action)}>
                {signal ? signal.label : <Skeleton width="5ch" />}
              </strong>
            </article>
            <article>
              <span>Confiance</span>
              <strong className={signalTone(signal?.action)}>
                {signal ? `${signal.confidence}/100` : <Skeleton width="5ch" />}
              </strong>
            </article>
            <article>
              <span>Range 52 semaines</span>
              <strong>
                {market ? `${market.stats.low52w.toFixed(2)} – ${market.stats.high52w.toFixed(2)}` : <Skeleton width="10ch" />}
              </strong>
            </article>
          </div>
        </div>
      </section>

      {error ? <div className="status-banner status-banner--error">{error}</div> : null}

      <section className="dashboard-grid">
        <article className="panel panel--chart">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Prix</p>
              <h2>Lecture graphique orientée décision</h2>
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

          {market ? (
            <div className="market-chart-wrap">
              <MarketChart points={points} />
            </div>
          ) : (
            <div className="chart-placeholder" />
          )}
          <NewsRail items={news?.items.slice(0, 6) ?? []} />
          <div className="mini-trend">
            <svg viewBox="0 0 320 60" preserveAspectRatio="none">
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
              <strong>{market ? formatPrice(market.stats.latestClose, market.currency) : <Skeleton width="6ch" />}</strong>
            </article>
            <article>
              <span>Variation</span>
              <strong className={isPositive ? 'positive' : 'negative'}>
                {market ? `${changePercent.toFixed(2)}%` : <Skeleton width="5ch" />}
              </strong>
            </article>
            <article>
              <span>RSI 14j</span>
              <strong>{market ? market.stats.rsi14.toFixed(1) : <Skeleton width="4ch" />}</strong>
            </article>
            <article>
              <span>Indice buy / sell</span>
              <strong className={signalTone(signal?.action)}>
                {signal ? `${signal.confidence}/100` : <Skeleton width="5ch" />}
              </strong>
            </article>
            <article>
              <span>Score technique</span>
              <strong className={signalTone(signal?.action)}>
                {signal ? signal.technicalScore.toFixed(2) : <Skeleton width="4ch" />}
              </strong>
            </article>
            <article>
              <span>Score news</span>
              <strong className={signalTone(signal?.action)}>
                {signal ? signal.newsScore.toFixed(2) : <Skeleton width="4ch" />}
              </strong>
            </article>
          </div>

          <div className="summary-copy">
            <p className="eyebrow">Decision engine</p>
            <div>
              {signal?.summary ? (
                signal.summary.split('\n').map((line, index) => <p key={`${line}-${index}`}>{line}</p>)
              ) : (
                <p>
                  Le moteur de décision combine tendance, momentum, RSI, volumes et lecture des news pour
                  produire un signal achat, conservation ou vente.
                </p>
              )}
            </div>
          </div>

          <div className="summary-copy">
            <p className="eyebrow">Moteur news</p>
            <div>
              <p>{signal?.llmUsed ? `LLM OpenRouter — ${signal.model}` : 'Fallback heuristique sur les headlines'}</p>
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
              <p className="eyebrow">Range 52 semaines</p>
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
        <article className="panel panel--news-list">
          <div className="panel__header">
            <div>
              <p className="eyebrow">Actualités</p>
              <h2>Flux éditorial</h2>
            </div>
          </div>
          <div className="headline-list">
            {(news?.items ?? []).slice(0, 6).map((item, index) => (
              <a className="headline-item" href={item.link} key={`${item.link}-${index}`} rel="noreferrer" target="_blank">
                <span>{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <strong>{item.title}</strong>
                  <small>
                    {item.source} · {new Date(item.published).toLocaleDateString('fr-FR')}
                  </small>
                </div>
                <span>↗</span>
              </a>
            ))}
          </div>
        </article>
      </section>
    </main>
  );
}
