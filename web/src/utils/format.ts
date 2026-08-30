import type { Money } from '../contracts/avalGateway.ts';

export function formatMoney(money: Money): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: money.currency,
    minimumFractionDigits: money.scale,
    maximumFractionDigits: money.scale,
  }).format(money.minorUnits / 10 ** money.scale);
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value));
}

export function shortHash(value: string): string {
  if (value.length <= 26) return value;
  return `${value.slice(0, 14)}…${value.slice(-8)}`;
}
