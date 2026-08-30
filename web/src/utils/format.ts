import type { Money } from '../contracts/avalGateway.ts';

/**
 * The wire speaks snake_case and the formatter speaks camelCase. One adapter, so a
 * screen never reaches for `minor_units / 10 ** scale` by hand and rounds it its own way.
 */
export function toMoney(value: { minor_units: number; currency: string; scale: number }): Money {
  return { minorUnits: value.minor_units, currency: value.currency, scale: value.scale };
}

export function formatMoney(money: Money): string {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: money.currency,
    minimumFractionDigits: money.scale,
    maximumFractionDigits: money.scale,
  }).format(money.minorUnits / 10 ** money.scale);
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value));
}

export function shortHash(value: string): string {
  if (value.length <= 26) return value;
  return `${value.slice(0, 14)}…${value.slice(-8)}`;
}
