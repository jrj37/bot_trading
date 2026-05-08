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
  if (index < size - 1) {
    return null;
  }

  const window = points.slice(index - (size - 1), index + 1);
  return window.reduce((sum, point) => sum + point.close, 0) / window.length;
}

export function MarketChart({ points }: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const movingAverageRef = useRef<ISeriesApi<'Line'> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: '#f4efe6' },
        textColor: '#2e2a25',
        fontFamily: 'Space Grotesk, sans-serif',
      },
      grid: {
        vertLines: { color: 'rgba(46, 42, 37, 0.06)' },
        horzLines: { color: 'rgba(46, 42, 37, 0.08)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: 'rgba(46, 42, 37, 0.12)',
      },
      timeScale: {
        borderColor: 'rgba(46, 42, 37, 0.12)',
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#f28a2e',
      downColor: '#5b6472',
      borderVisible: false,
      wickUpColor: '#f28a2e',
      wickDownColor: '#5b6472',
    });

    const movingAverageSeries = chart.addSeries(LineSeries, {
      color: '#2f353d',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    candleSeries.setData(
      points.map((point) => ({
        time: point.time as Time,
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
      }))
    );

    movingAverageSeries.setData(
      points
        .map((point, index) => {
          const averageValue = averageWindow(points, index, 50);
          if (averageValue == null) {
            return null;
          }

          return {
            time: point.time as Time,
            value: averageValue,
          };
        })
        .filter((point): point is { time: Time; value: number } => point !== null)
    );

    chart.timeScale().fitContent();

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
  }, [points]);

  return <div className="market-chart" ref={containerRef} />;
}
