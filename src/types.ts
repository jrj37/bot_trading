export interface MarketPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MarketStats {
  latestClose: number;
  changePercent: number;
  movingAverage50: number;
  high52w: number;
  low52w: number;
  averageVolume20: number;
  rsi14: number;
  priceVsMa50Percent: number;
  volumeRatio20: number;
}

export interface MarketResponse {
  symbol: string;
  currency: string;
  exchangeName: string;
  regularMarketPrice: number;
  points: MarketPoint[];
  stats: MarketStats;
}

export interface NewsItem {
  title: string;
  link: string;
  source: string;
  published: string;
}

export interface NewsResponse {
  symbol: string;
  source: string;
  summary: string | null;
  items: NewsItem[];
}

export interface SignalResponse {
  symbol: string;
  action: 'buy' | 'hold' | 'sell';
  label: string;
  confidence: number;
  score: number;
  summary: string;
  technicalScore: number;
  newsScore: number;
  technicalConfidence: number;
  newsConfidence: number;
  technicalDrivers: string[];
  newsDrivers: string[];
  llmUsed: boolean;
  model: string;
}
