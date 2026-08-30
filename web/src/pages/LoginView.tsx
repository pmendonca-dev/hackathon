import { useEffect, useRef, useState, type FormEvent } from 'react';
import { LogIn, ShieldCheck } from 'lucide-react';

import type { UiLoginRequest, UiRole } from '../contracts/avalGateway.ts';
import type { AvalErrorPresentation } from '../errors/avalError.ts';
import { RuntimeFailure } from '../components/RuntimeFailure.tsx';
import { Badge, Button, Panel } from '../components/ui.tsx';

const ROLE_LABEL: Record<UiRole, string> = {
  merchant: 'Merchant',
  holder: 'Titular',
  auditor: 'Auditor',
  operator: 'Operador',
};

export function LoginView({
  loading,
  error,
  onLogin,
}: {
  loading: boolean;
  error: AvalErrorPresentation | null;
  onLogin(request: UiLoginRequest): Promise<void>;
}) {
  const [role, setRole] = useState<UiRole>('holder');
  const [credential, setCredential] = useState('');
  const roleSelectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    roleSelectRef.current?.focus();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await onLogin({ role, credential });
    } finally {
      setCredential('');
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl items-center px-5 py-12">
      <div className="w-full space-y-4">
        <header className="page-heading">
          <div>
            <p className="eyebrow">AVAL · browser BFF</p>
            <h1>Sessão local com projeção restrita por papel.</h1>
            <p>A credencial é enviada uma vez ao mesmo origin e removida do campo após a resposta.</p>
          </div>
          <Badge tone="verify">SESSÃO SEGURA</Badge>
        </header>

        {error && <RuntimeFailure error={error} />}

        <Panel eyebrow="Acesso local" title="Entrar na projeção autorizada" action={<ShieldCheck size={19} className="text-verify" aria-hidden="true" />}>
          <form onSubmit={(event) => void submit(event)} className="space-y-4" aria-busy={loading}>
            <label className="block" htmlFor="login-role">
              <span className="eyebrow">Papel</span>
              <select
                ref={roleSelectRef}
                id="login-role"
                className="form-control"
                value={role}
                onChange={(event) => setRole(event.target.value as UiRole)}
                disabled={loading}
              >
                {(Object.keys(ROLE_LABEL) as UiRole[]).map((candidate) => (
                  <option key={candidate} value={candidate}>{ROLE_LABEL[candidate]}</option>
                ))}
              </select>
            </label>
            <label className="block" htmlFor="login-credential">
              <span className="eyebrow">Credencial local</span>
              <input
                id="login-credential"
                className="form-control"
                type="password"
                autoComplete="off"
                aria-describedby="login-credential-help"
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
                required
                disabled={loading}
              />
              <span id="login-credential-help" className="mt-1.5 block text-[11px] leading-relaxed text-fg-mute">
                Usada uma vez no mesmo origin e removida deste campo após a resposta.
              </span>
            </label>
            <Button type="submit" disabled={loading || !credential.trim()}>
              <LogIn size={14} aria-hidden="true" />
              {loading ? 'Iniciando sessão' : 'Entrar'}
            </Button>
          </form>
        </Panel>

        <p className="safe-note"><ShieldCheck size={15} aria-hidden="true" />A aplicação não grava sessão, credencial ou proteção de mutação em storage do browser.</p>
      </div>
    </div>
  );
}
