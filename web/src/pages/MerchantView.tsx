import { useState } from 'react';
import { BadgeCheck, EyeOff, ScanLine } from 'lucide-react';
import { useStore } from '../domain/store';
import { money } from '../domain/policy';
import { Page, TopBar } from '../components/Shell';
import { Badge, Button, Field, Panel } from '../components/ui';
import { CheckList } from '../components/Verification';
import type { Check } from '../domain/policy';

const RECEIPT_CHECKS: Check[] = [
  { label: 'Signature valid', passed: true, note: 'ES256 · aval.local' },
  { label: 'Offer valid', passed: true, note: 'merchant_authorization' },
  { label: 'Decision valid', passed: true, note: 'dh_8b31af02' },
  { label: 'Terms match', passed: true, note: 'hash equal' },
  { label: 'Revocation status valid', passed: true, note: 'epoch 0' },
];

/** Fields the principal sees that are deliberately absent from the merchant payload. */
const WITHHELD = [
  ['Monthly budget', 'A merchant does not need to know how much room is left.'],
  ['Accumulated spend', 'Spend history across other merchants is not their business.'],
  ['principal_id', 'The buyer is verified, not identified.'],
  ['mandate_id', 'The authority reference stays inside the authorization layer.'],
];

export function MerchantView() {
  const { state, toast } = useStore();
  const [verified, setVerified] = useState(false);
  const attempt = state.attempts[0];

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Merchant']}
        title="Merchant view"
        subtitle="Exactly what VuelaYa receives — and nothing more"
      />
      <Page>
        <div className="grid gap-3 lg:grid-cols-[1.15fr_1fr]">
          {/* The receipt */}
          <Panel eyebrow="Authorization receipt" title="VuelaYa" bodyClass="">
            <div className="flex flex-col items-center gap-3 border-b border-line px-5 py-8 text-center">
              <span className="flex size-12 items-center justify-center rounded-full border border-verify/30 bg-verify/8">
                <BadgeCheck size={22} className="text-verify" strokeWidth={1.75} />
              </span>
              <div className="mono text-[13px] font-bold tracking-[0.18em] text-verify uppercase">
                Authorization verified
              </div>
              <div className="mono text-[30px] leading-none tracking-tight text-fg">
                {money(attempt.amount, attempt.currency)}
              </div>
            </div>

            <div className="px-5 py-1">
              <Field label="Decision" tone="allow">
                AUTHORIZED
              </Field>
              <Field label="Amount">{money(attempt.amount, attempt.currency)}</Field>
              <Field label="Category">TRAVEL</Field>
              <Field label="Offer">{attempt.merchant}</Field>
              <Field label="Decision handle">{attempt.decisionHandle}</Field>
              <Field label="Terms hash">{attempt.termsHash}</Field>
              <Field label="Signature" tone="verify">
                VALID
              </Field>
            </div>

            <div className="border-t border-line p-5">
              <Button
                variant="ghost"
                className="w-full"
                onClick={() => {
                  setVerified(true);
                  toast({
                    tone: 'verify',
                    title: 'Receipt verified',
                    body: 'Five checks passed against the published key.',
                  });
                }}
              >
                <ScanLine size={13} />
                {verified ? 'Verify again' : 'Verify receipt'}
              </Button>
              {verified && (
                <div className="anim-rise mt-4">
                  <CheckList checks={RECEIPT_CHECKS} />
                </div>
              )}
            </div>
          </Panel>

          {/* What is deliberately absent. Showing the hole is the feature. */}
          <div className="space-y-3">
            <Panel
              eyebrow="Privacy"
              title="Withheld from this payload"
              action={<Badge tone="neutral" size="sm">NOT SENT</Badge>}
            >
              <p className="mb-4 text-[13px] leading-relaxed text-fg-mute">
                The merchant gets enough to prove the charge was authorized, and no more. A receipt
                that leaked the buyer's budget would be a receipt that leaked the buyer.
              </p>
              <ul className="space-y-3">
                {WITHHELD.map(([field, why]) => (
                  <li key={field} className="flex gap-3">
                    <EyeOff size={13} className="mt-0.5 shrink-0 text-fg-faint" />
                    <div className="min-w-0">
                      <div className="mono text-[11px] text-fg-dim line-through decoration-fg-faint">
                        {field}
                      </div>
                      <p className="mt-0.5 text-[12px] leading-relaxed text-fg-mute">{why}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel eyebrow="Same event" title="Three views of one truth">
              <ul className="space-y-2.5 text-[13px]">
                <ViewRow role="Merchant" gets="Decision, amount, category, handle, signature." />
                <ViewRow role="Principal" gets="Everything above, plus budget, mandate and history." />
                <ViewRow role="Auditor" gets="The full ledger chain with hashes and actors." />
              </ul>
            </Panel>
          </div>
        </div>
      </Page>
    </>
  );
}

function ViewRow({ role, gets }: { role: string; gets: string }) {
  return (
    <li className="flex gap-3 border-b border-line/60 pb-2.5 last:border-0 last:pb-0">
      <span className="mono w-[68px] shrink-0 text-[10px] tracking-wider text-fg-mute uppercase">
        {role}
      </span>
      <span className="text-[12px] leading-relaxed text-fg-dim">{gets}</span>
    </li>
  );
}
