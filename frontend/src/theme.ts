import { useEffect, useState } from 'react';

// Categorical palette (validated light/dark steps), in fixed order.
const LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
const DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];

export interface ChartTheme {
  dark: boolean;
  series: string[];
  other: string;
  grid: string;
  axis: string;
  surface: string;
  text: string;
}

function build(dark: boolean): ChartTheme {
  return dark
    ? { dark, series: DARK, other: '#6b6a66', grid: '#2e2e2c', axis: '#a3a29c', surface: '#1a1a19', text: '#f2f2f0' }
    : { dark, series: LIGHT, other: '#a8a7a2', grid: '#e7e6e2', axis: '#6b6a66', surface: '#ffffff', text: '#1b1b1a' };
}

export function useChartTheme(): ChartTheme {
  const query = '(prefers-color-scheme: dark)';
  const [dark, setDark] = useState(() => typeof window !== 'undefined' && window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const fn = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener('change', fn);
    return () => mq.removeEventListener('change', fn);
  }, []);
  return build(Boolean(dark));
}
