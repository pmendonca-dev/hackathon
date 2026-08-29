import { useEffect } from 'react';
import { X } from 'lucide-react';
import { useStore } from '../domain/store';
import type { Toast } from '../domain/store';
import { toneBg, toneText } from './ui';

export function Toasts() {
  const { state, dismissToast } = useStore();
  return (
    <div className="pointer-events-none fixed right-5 bottom-5 z-[60] flex w-[340px] flex-col gap-2">
      {state.toasts.slice(-4).map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={() => dismissToast(t.id)} />
      ))}
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  useEffect(() => {
    const id = window.setTimeout(onDismiss, 5000);
    return () => clearTimeout(id);
  }, [onDismiss]);

  return (
    <div className="anim-slide-in pointer-events-auto flex gap-3 overflow-hidden rounded-lg border border-line bg-ink-800 p-3.5 shadow-xl">
      <span className={`w-0.5 shrink-0 rounded-full ${toneBg[toast.tone]}`} />
      <div className="min-w-0 flex-1">
        <div className={`mono text-[11px] font-semibold uppercase ${toneText[toast.tone]}`}>
          {toast.title}
        </div>
        {toast.body && (
          <p className="mt-1 text-[12px] leading-relaxed text-fg-dim">{toast.body}</p>
        )}
      </div>
      <button
        onClick={onDismiss}
        className="h-fit shrink-0 rounded p-0.5 text-fg-faint transition-colors hover:text-fg"
        aria-label="Dismiss"
      >
        <X size={13} />
      </button>
    </div>
  );
}
