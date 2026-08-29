import type { ButtonHTMLAttributes, ReactNode } from 'react';

import type { Tone } from '../contracts/avalGateway.ts';

const toneClass: Record<Tone, string> = {
  allow: 'border-allow/35 bg-allow/10 text-allow',
  escalate: 'border-escalate/35 bg-escalate/10 text-escalate',
  deny: 'border-deny/35 bg-deny/10 text-deny',
  verify: 'border-verify/35 bg-verify/10 text-verify',
  hold: 'border-hold/35 bg-hold/10 text-hold',
  neutral: 'border-line bg-white/3 text-fg-mute',
};

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={`mono inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${toneClass[tone]}`}>
      {children}
    </span>
  );
}

export function Panel({
  eyebrow,
  title,
  action,
  children,
  className = '',
}: {
  eyebrow?: string;
  title: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`overflow-hidden rounded-2xl border border-line bg-ink-850 ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
          <h2 className="font-display text-base font-semibold tracking-tight">{title}</h2>
        </div>
        {action}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Field({ label, children, mono = true }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="grid gap-1 border-b border-line/70 py-3 last:border-0 sm:grid-cols-[minmax(8rem,0.7fr)_1.3fr] sm:items-baseline sm:gap-5">
      <dt className="eyebrow">{label}</dt>
      <dd className={`min-w-0 break-words text-[13px] text-fg ${mono ? 'mono' : ''}`}>{children}</dd>
    </div>
  );
}

export function Button({
  children,
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: 'primary' | 'ghost' | 'danger';
}) {
  const styles = {
    primary: 'border-allow bg-allow text-ink-950 hover:bg-allow/85',
    ghost: 'border-line-hi bg-ink-800 text-fg hover:bg-ink-750',
    danger: 'border-deny/50 bg-deny/10 text-deny hover:bg-deny/16',
  };
  return (
    <button
      className={`mono inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-3.5 py-2 text-[11px] font-semibold uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function EmptyNotice({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line-hi px-6 py-10 text-center">
      <h3 className="font-display text-sm font-semibold">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-[13px] leading-relaxed text-fg-mute">{body}</p>
    </div>
  );
}
