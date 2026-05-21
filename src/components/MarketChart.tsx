import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';

import type { MarketPoint } from '../types';

interface MarketChartProps {
  points: MarketPoint[];
}

function averageWindow(points: MarketPoint[], index: number, size: number): number | null {
  if (index < size - 1) return null;
  const window = points.slice(index - (size - 1), index + 1);
  return window.reduce((sum, point) => sum + point.close, 0) / window.length;
}

const CHART_THEME = {
  bg: '#0e1011',
  text: '#c9c1ad',
  grid: 'rgba(236, 229, 212, 0.05)',
  border: 'rgba(236, 229, 212, 0.1)',
  up: '#d49b54',
  down: '#8b94a0',
  ma: '#f6f1e6',
};

export function MarketChart({ points }: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const movingAverageRef = useRef<ISeriesApi<'Line'> | null>(null);

  // Create chart once
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: CHART_THEME.bg },
        textColor: CHART_THEME.text,
        fontFamily: 'Geist Mono, ui-monospace, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: CHART_THEME.grid },
        horzLines: { color: CHART_THEME.grid },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: CHART_THEME.border, width: 1, style: 3 },
        horzLine: { color: CHART_THEME.border, width: 1, style: 3 },
      },
      rightPriceScale: { borderColor: CHART_THEME.border, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: CHART_THEME.border, timeVisible: false, secondsVisible: false },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: CHART_THEME.up,
      downColor: CHART_THEME.down,
      borderVisible: false,
      wickUpColor: CHART_THEME.up,
      wickDownColor: CHART_THEME.down,
    });

    const movingAverageSeries = chart.addSeries(LineSeries, {
      color: CHART_THEME.ma,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    candleRef.current = candleSeries;
    movingAverageRef.current = movingAverageSeries;

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      movingAverageRef.current = null;
      candleRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, []);

  // Update data without re-creating chart (eliminates flicker)
  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleRef.current;
    const movingAverageSeries = movingAverageRef.current;
    if (!chart || !candleSeries || !movingAverageSeries || points.length === 0) return;

    candleSeries.setData(
      points.map((point) => ({
        time: point.time as Time,
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
      })),
    );

    movingAverageSeries.setData(
      points
        .map((point, index) => {
          const value = averageWindow(points, index, 50);
          if (value == null) return null;
          return { time: point.time as Time, value };
        })
        .filter((p): p is { time: Time; value: number } => p !== null),
    );

    chart.timeScale().fitContent();
  }, [points]);

  return <div className="market-chart" ref={containerRef} />;
}
