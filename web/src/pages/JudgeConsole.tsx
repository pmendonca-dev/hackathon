import { Play, Loader, Flame, RotateCcw } from 'lucide-react';
import { useStore } from '../domain/store';
import { money } from '../domain/policy';
import type { JudgeTest } from '../domain/types';
import { Page, TopBar } from '../components/Shell';
import { Badge, Button, Panel, toneText } from '../components/ui';

const SCENARIOS: { id: string; label: string; hint: string }[] = [
  { id: '01', label: 'Happy path', hint: '$130 flows end to end' },
  { id: '02', label: 'Escalation', hint: '$300 waits for a signature' },
  { id: '03', label: 'Revocation', hint: 'authority pulled mid-flight' },
  { id: '04', label: 'PSP failure', hint: 'held, not declined' },
  { id: '05', label: 'Fake webhook', hint: 'forged settlement' },
  { id: '06', label: 'Replay attack', hint: 'spent nonce resent' },
  { id: '07', label: 'Reservation griefing', hint: 'parallel holds' },
];

export function JudgeConsole() {
  const { state, metrics, runJudgeTest, runScenario, reset } = useStore();
  const ran = state.judgeTests.filter((t) => t.state === 'done').length;

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Judge Console']}
        title="Judge Console"
        subtitle="Trial by fire"
        action={
          <Button variant="quiet" onClick={reset}>
            <RotateCcw size={13} />
            Reset state
          </Button>
        }
      />

      <div className="pb-[104px]">
        <Page>
          {/* Scenario controller: one click puts the whole product in a state. */}
          <Panel
            eyebrow="Demo scenario"
            title="Drive the system into a state"
            action={
              <span className="mono text-[10px] text-fg-faint">
                {state.activeScenario ? `RUNNING ${state.activeScenario}` : 'IDLE'}
              </span>
            }
          >
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
              {SCENARIOS.map((s) => {
                const active = state.activeScenario === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => runScenario(s.id)}
                    className={`flex flex-col gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                      active
                        ? 'border-allow/45 bg-allow/8'
                        : 'border-line bg-ink-800 hover:border-line-hi hover:bg-ink-750'
                    }`}
                  >
                    <span className="flex items-baseline gap-2">
                      <span className={`mono text-[10px] ${active ? 'text-allow' : 'text-fg-faint'}`}>
                        {s.id}
                      </span>
                      <span className="text-[13px] font-medium">{s.label}</span>
                    </span>
                    <span className="text-[11px] text-fg-mute">{s.hint}</span>
                  </button>
                );
              })}
            </div>
          </Panel>

          {/* Attack grid */}
          <div className="mt-7 mb-3 flex items-baseline justify-between gap-4">
            <h2 className="flex items-center gap-2 font-display text-[17px] font-semibold tracking-tight">
              <Flame size={15} className="text-escalate" />
              Trial by fire
            </h2>
            <span className="mono text-[10px] text-fg-mute">
              {ran} / {state.judgeTests.length} RUN
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {state.judgeTests.map((t) => (
              <TestCard key={t.id} test={t} onRun={() => runJudgeTest(t.id)} />
            ))}
          </div>

          <p className="mt-5 max-w-2xl text-[12px] leading-relaxed text-fg-mute">
            Every test is meant to break the layer. None of them changes the invariant at the bottom
            of this screen: an agent may act for a human, but it can never exceed the authority it
            was handed.
          </p>
        </Page>
      </div>

      <MetricsBar metrics={metrics} />
    </>
  );
}

function TestCard({ test, onRun }: { test: JudgeTest; onRun: () => void }) {
  const running = test.state === 'running';
  const done = test.state === 'done';
  const ink = toneText[test.tone];

  return (
    <article
      className={`flex flex-col rounded-xl border bg-ink-850 p-4 transition-colors ${
        done
          ? test.tone === 'deny'
            ? 'border-deny/30'
            : test.tone === 'hold'
              ? 'border-hold/30'
              : 'border-verify/30'
          : 'border-line'
      }`}
    >
      <h3 className="text-[13px] font-semibold">{test.name}</h3>
      <p className="mt-1 flex-1 text-[11px] leading-relaxed text-fg-mute">{test.description}</p>

      <div className="mt-3.5 border-t border-line pt-3">
        <div className="eyebrow mb-1">Expected</div>
        <div className={`mono text-[10px] leading-snug font-semibold ${ink}`}>{test.expected}</div>
      </div>

      {done && test.detail && (
        <p className="anim-rise mt-3 border-t border-line pt-3 text-[11px] leading-relaxed text-fg-dim">
          {test.detail}
        </p>
      )}

      <Button
        variant={done ? 'quiet' : 'ghost'}
        size="sm"
        className="mt-3.5 w-full"
        onClick={onRun}
        disabled={running}
      >
        {running ? (
          <>
            <Loader size={11} className="animate-spin" />
            Running
          </>
        ) : done ? (
          <>
            <RotateCcw size={11} />
            Run again
          </>
        ) : (
          <>
            <Play size={11} />
            Run test
          </>
        )}
      </Button>

      {done && (
        <div className="mt-2.5 flex justify-center">
          <Badge tone={test.tone} size="sm" dot>
            {test.observed?.replace(/_/g, ' ')}
          </Badge>
        </div>
      )}
    </article>
  );
}

function MetricsBar({ metrics }: { metrics: ReturnType<typeof useStore>['metrics'] }) {
  const items = [
    { label: '/authorize p99', value: `${metrics.authorizeP99} ms`, target: metrics.authorizeP99 < 60 },
    { label: '/capture p99', value: `${metrics.captureP99} ms`, target: metrics.captureP99 < 80 },
    {
      label: 'Revocation propagation',
      value: `${metrics.revocationPropagation.toFixed(1)} s`,
      target: metrics.revocationPropagation < 1,
    },
    { label: 'IN_DOUBT attempts', value: String(metrics.inDoubt), target: true },
    { label: 'Ledger divergence', value: String(metrics.ledgerDivergence), target: metrics.ledgerDivergence === 0 },
    {
      label: 'Unauthorized spend',
      value: money(metrics.unauthorizedSpend),
      target: metrics.unauthorizedSpend === 0,
      emphasis: true,
    },
  ];

  return (
    <footer className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-ink-900/95 backdrop-blur-md lg:left-[236px]">
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-8 gap-y-3 px-6 py-3.5 lg:px-8">
        <span className="eyebrow flex items-center gap-1.5 text-allow">
          <span className="size-1.5 animate-pulse rounded-full bg-allow" />
          Live system metrics
        </span>
        <div className="flex flex-1 flex-wrap items-center gap-x-7 gap-y-2.5">
          {items.map((m) => (
            <div key={m.label} className="leading-tight">
              <div className="eyebrow">{m.label}</div>
              <div
                className={`mono mt-0.5 text-[13px] ${
                  m.emphasis ? 'font-semibold text-allow' : m.target ? 'text-fg' : 'text-escalate'
                }`}
              >
                {m.value}
              </div>
            </div>
          ))}
        </div>
      </div>
    </footer>
  );
}
