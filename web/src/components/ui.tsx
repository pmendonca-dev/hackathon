import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { X } from 'lucide-react';

// ── Tone system ─────────────────────────────────────────────────────────────
// One colour, one meaning, everywhere in the product:
//   allow    authority granted        escalate  human decision required
//   deny     refused by policy        verify    cryptographic verification
//   hold     indeterminate            neutral   inert / historical
export type Tone = 'allow' | 'escalate' | 'deny' | 'verify' | 'hold' | 'neutral';

export const toneRing: Record<Tone, string> = {
  allow: 'text-allow border-allow/35 bg-allow/8',
  escalate: 'text-escalate border-escalate/35 bg-escalate/8',
  deny: 'text-deny border-deny/35 bg-deny/8',
  verify: 'text-verify border-verify/35 bg-verify/8',
  hold: 'text-hold border-hold/35 bg-hold/8',
  neutral: 'text-fg-mute border-line bg-white/2',
};

export const toneText: Record<Tone, string> = {
  allow: 'text-allow',
  escalate: 'text-escalate',
  deny: 'text-deny',
  verify: 'text-verify',
  hold: 'text-hold',
  neutral: 'text-fg-mute',
};

export const toneBg: Record<Tone, string> = {
  allow: 'bg-allow',
  escalate: 'bg-escalate',
  deny: 'bg-deny',
  verify: 'bg-verify',
  hold: 'bg-hold',
  neutral: 'bg-fg-faint',
};

/** Maps every status string in the product to exactly one tone. */
export function toneFor(status: string): Tone {
  switch (status) {
    case 'ALLOW':
    case 'ACTIVE':
    case 'SETTLED':
    case 'OK':
    case 'AUTHORIZED':
    case 'ONLINE':
    case 'OPERATIONAL':
    case 'VERIFIED':
    case 'VALID':
      return 'allow';
    case 'ESCALATE':
    case 'ESCALATED':
    case 'HELD':
    case 'AWAITING_CAPTURE':
    case 'UNDER_REVIEW':
      return 'escalate';
    case 'DENY':
    case 'DENIED':
    case 'DECLINED':
    case 'REVOKED':
    case 'REJECTED':
    case 'OFFLINE':
    case 'UPHELD':
      return 'deny';
    case 'IN_DOUBT':
    case 'IN_CONFIRMATION':
    case 'RECONCILING':
    case 'CONFIRMING':
    case 'COMPENSATED':
      return 'hold';
    default:
      return 'neutral';
  }
}

// ── Badge ───────────────────────────────────────────────────────────────────
export function Badge({
  children,
  tone,
  size = 'md',
  dot = false,
}: {
  children: ReactNode;
  tone?: Tone;
  size?: 'sm' | 'md';
  dot?: boolean;
}) {
  const t = tone ?? toneFor(String(children));
  return (
    <span
      className={`mono inline-flex shrink-0 items-center gap-1.5 rounded-full border font-medium uppercase ${
        toneRing[t]
      } ${size === 'sm' ? 'px-2 py-0.5 text-[9px]' : 'px-2.5 py-1 text-[10px]'}`}
    >
      {dot && <span className={`size-1.5 rounded-full ${toneBg[t]}`} />}
      {children}
    </span>
  );
}

// ── Status dot with a live pulse ────────────────────────────────────────────
export function StatusDot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  return (
    <span className="relative inline-flex size-2 shrink-0">
      <span className={`size-2 rounded-full ${toneBg[tone]}`} />
      {pulse && (
        <span
          className={`anim-pulse absolute inset-0 rounded-full ${toneText[tone]}`}
          style={{ backgroundColor: 'currentColor' }}
        />
      )}
    </span>
  );
}

// ── Card ────────────────────────────────────────────────────────────────────
export function Card({
  children,
  className = '',
  as: As = 'div',
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: 'div' | 'button' | 'li';
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <As
      className={`rounded-xl border border-line bg-ink-850 ${className}`}
      {...(rest as Record<string, unknown>)}
    >
      {children}
    </As>
  );
}

export function Panel({
  eyebrow,
  title,
  action,
  children,
  className = '',
  bodyClass = 'p-5',
}: {
  eyebrow?: string;
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`overflow-hidden rounded-xl border border-line bg-ink-850 ${className}`}>
      {(title || eyebrow || action) && (
        <header className="flex items-center justify-between gap-4 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
            {title && (
              <h2 className="truncate font-display text-[15px] font-semibold tracking-tight text-fg">
                {title}
              </h2>
            )}
          </div>
          {action}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

// ── Button ──────────────────────────────────────────────────────────────────
export function Button({
  children,
  variant = 'ghost',
  size = 'md',
  className = '',
  ...rest
}: {
  children: ReactNode;
  variant?: 'primary' | 'ghost' | 'danger' | 'quiet';
  size?: 'sm' | 'md';
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const variants = {
    primary:
      'bg-allow text-ink-950 border-allow hover:bg-allow/88 font-semibold disabled:bg-allow/30 disabled:text-ink-950/50',
    ghost: 'bg-ink-800 text-fg border-line hover:border-line-hi hover:bg-ink-750',
    danger: 'bg-deny/10 text-deny border-deny/40 hover:bg-deny/16',
    quiet: 'bg-transparent text-fg-dim border-transparent hover:text-fg hover:bg-white/4',
  };
  return (
    <button
      className={`mono inline-flex items-center justify-center gap-2 rounded-lg border uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
        variants[variant]
      } ${size === 'sm' ? 'px-2.5 py-1.5 text-[10px]' : 'px-3.5 py-2 text-[11px]'} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

// ── Key/value row, the workhorse of every detail surface ────────────────────
export function Field({
  label,
  children,
  mono = true,
  tone,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
  tone?: Tone;
}) {
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line/60 py-2.5 last:border-0">
      <span className="eyebrow shrink-0">{label}</span>
      <span
        className={`min-w-0 truncate text-right text-[13px] ${mono ? 'mono' : ''} ${
          tone ? toneText[tone] : 'text-fg'
        }`}
      >
        {children}
      </span>
    </div>
  );
}

// ── Drawer ──────────────────────────────────────────────────────────────────
export function Drawer({
  open,
  onClose,
  title,
  eyebrow,
  children,
  width = 'max-w-xl',
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  eyebrow?: string;
  children: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-ink-950/70 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={`anim-slide-in relative flex h-full w-full ${width} flex-col border-l border-line bg-ink-900 shadow-2xl`}
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
            <h2 className="font-display text-lg font-semibold tracking-tight">{title}</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-fg-mute transition-colors hover:bg-white/5 hover:text-fg"
            aria-label="Close panel"
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </aside>
    </div>
  );
}

// ── Empty state ─────────────────────────────────────────────────────────────
export function Empty({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="text-fg-faint">{icon}</div>
      <h3 className="font-display text-sm font-semibold text-fg-dim">{title}</h3>
      <p className="max-w-xs text-[13px] leading-relaxed text-fg-mute">{body}</p>
    </div>
  );
}
