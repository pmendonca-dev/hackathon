export type AvalErrorAction = 'retry-read' | 'check-availability' | 'check-status' | 'none';
export type AvalErrorTone = 'deny' | 'hold' | 'verify' | 'escalate' | 'neutral';

export interface AvalErrorPresentation {
  status: number | null;
  code: string;
  title: string;
  message: string;
  recovery: string;
  action: AvalErrorAction;
  tone: AvalErrorTone;
}

interface ErrorCopy {
  title: string;
  message: string;
  recovery: string;
  action?: AvalErrorAction;
  tone?: AvalErrorTone;
}

const ERROR_COPY: Record<string, ErrorCopy> = {
  ui_login_invalid: {
    title: 'Acesso negado',
    message: 'A credencial local é inválida ou este papel não está habilitado.',
    recovery: 'Confirme o papel e digite novamente a credencial local.',
    tone: 'deny',
  },
  ui_session_required: {
    title: 'Sessão necessária',
    message: 'Uma sessão válida é necessária para acessar esta projeção.',
    recovery: 'A sessão local foi descartada. Entre novamente; nenhuma operação foi presumida pelo browser.',
    tone: 'deny',
  },
  csrf_invalid: {
    title: 'Mutação bloqueada',
    message: 'A proteção da sessão é inválida e a ação não foi executada.',
    recovery: 'A sessão local foi descartada. Entre novamente antes de iniciar outra ação.',
    tone: 'deny',
  },
  ui_role_not_authorized: {
    title: 'Projeção não autorizada',
    message: 'Este papel não possui acesso à projeção ou ação solicitada.',
    recovery: 'Use somente a visão atribuída à sessão atual.',
    tone: 'deny',
  },
  idempotency_unavailable: {
    title: 'Bloqueio seguro ativo',
    message: 'A idempotência durável está indisponível e a ação foi bloqueada.',
    recovery: 'Verifique a disponibilidade; não repita automaticamente a mutação.',
    tone: 'deny',
  },
  audit_unavailable: {
    title: 'Auditoria indisponível',
    message: 'A trilha de auditoria durável está indisponível.',
    recovery: 'Verifique a disponibilidade antes de tomar uma decisão baseada nesta leitura.',
    tone: 'deny',
  },
  mandate_revoked: {
    title: 'Mandato revogado',
    message: 'Este mandato foi revogado e não autoriza uma nova compra.',
    recovery: 'Consulte o titular antes de iniciar outra operação.',
    tone: 'deny',
  },
  mandate_expired: {
    title: 'Mandato expirado',
    message: 'Este mandato expirou e não pode autorizar o pagamento.',
    recovery: 'Solicite um mandato válido antes de tentar uma nova compra.',
    tone: 'deny',
  },
  merchant_out_of_scope: {
    title: 'Decisão humana necessária',
    message: 'O merchant está fora do escopo autorizado pelo mandato.',
    recovery: 'Encaminhe a compra para aprovação do titular; nenhuma captura foi iniciada.',
    tone: 'escalate',
  },
  policy_denied: {
    title: 'Compra recusada',
    message: 'A política viva recusou esta operação.',
    recovery: 'Revise a solicitação ou obtenha nova autorização antes de criar outra operação.',
    tone: 'deny',
  },
  revocation_unavailable: {
    title: 'Bloqueio seguro ativo',
    message: 'A verificação de revogação está indisponível; nenhum pagamento foi iniciado.',
    recovery: 'Verifique a disponibilidade do runtime. Não repita automaticamente o pagamento.',
    action: 'check-availability',
    tone: 'deny',
  },
  idempotency_in_flight: {
    title: 'Operação preservada',
    message: 'A operação original continua em andamento.',
    recovery: 'Consulte o status e o recibo; não envie uma segunda captura.',
    action: 'check-status',
    tone: 'hold',
  },
  idempotency_key_reused: {
    title: 'Solicitação rejeitada',
    message: 'A chave de idempotência já identifica outra solicitação.',
    recovery: 'Revise os dados e use uma nova chave somente para uma operação realmente nova.',
    tone: 'deny',
  },
  transaction_already_captured: {
    title: 'Operação preservada',
    message: 'Esta compra já foi capturada.',
    recovery: 'Consulte o status e o recibo da captura existente; não repita o pagamento.',
    action: 'check-status',
    tone: 'hold',
  },
  authorization_proof_invalid: {
    title: 'Solicitação rejeitada',
    message: 'A prova de autorização é inválida.',
    recovery: 'Não prossiga com a captura; obtenha uma autorização válida no runtime.',
    tone: 'deny',
  },
  vault_token_invalid: {
    title: 'Solicitação rejeitada',
    message: 'O token de pagamento é inválido.',
    recovery: 'Não reutilize o token; refaça a delegação pela API autorizada.',
    tone: 'deny',
  },
  request_invalid: {
    title: 'Solicitação rejeitada',
    message: 'A solicitação foi rejeitada antes da operação.',
    recovery: 'Revise os campos permitidos sem expor credenciais ou evidências na interface.',
    tone: 'deny',
  },
  reader_not_authorized: {
    title: 'Leitura não autorizada',
    message: 'Esta identidade está sem autorização para consultar a projeção.',
    recovery: 'Use uma identidade de holder ou auditor autorizada para esta leitura.',
    tone: 'deny',
  },
  signature_invalid: {
    title: 'Solicitação rejeitada',
    message: 'A assinatura da solicitação é inválida.',
    recovery: 'Assine novamente os bytes exatos da requisição antes de reenviar.',
    tone: 'deny',
  },
  profile_not_trusted: {
    title: 'Identidade não confiável',
    message: 'O perfil apresentado não é confiável para esta operação.',
    recovery: 'Use um perfil registrado pelo runtime.',
    tone: 'deny',
  },
};

const SAFE_CODE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/;
const SENSITIVE_CODE_PREFIX = /^(?:vt|proof)_/;

export function parseAvalErrorEnvelope(payload: unknown): string {
  if (
    typeof payload === 'object'
    && payload !== null
    && 'detail' in payload
    && typeof payload.detail === 'object'
    && payload.detail !== null
    && !Array.isArray(payload.detail)
    && 'code' in payload.detail
    && typeof payload.detail.code === 'string'
    && SAFE_CODE.test(payload.detail.code)
    && !SENSITIVE_CODE_PREFIX.test(payload.detail.code)
  ) {
    return payload.detail.code;
  }
  return 'request_invalid';
}

export function presentAvalError(error: { status: number; code: string }): AvalErrorPresentation {
  const known = ERROR_COPY[error.code];
  if (known) {
    const operationPreserved = error.status === 409;
    const safeBlock = error.status === 503;
    return {
      status: error.status,
      code: error.code,
      title: operationPreserved
        ? 'Operação preservada'
        : safeBlock
          ? 'Bloqueio seguro ativo'
          : known.title,
      message: known.message,
      recovery: operationPreserved
        ? 'Consulte o status e o recibo da operação original antes de qualquer nova ação.'
        : safeBlock
          ? 'Verifique a disponibilidade do runtime. Não repita automaticamente o pagamento.'
          : known.recovery,
      action: operationPreserved
        ? 'check-status'
        : safeBlock
          ? 'check-availability'
          : error.status === 422
            ? 'none'
            : known.action ?? 'none',
      tone: operationPreserved ? 'hold' : known.tone ?? 'deny',
    };
  }

  if (error.status === 503) {
    return {
      status: 503,
      code: error.code,
      title: 'Serviço indisponível',
      message: 'O runtime não confirmou uma decisão segura.',
      recovery: 'Verifique a disponibilidade. Não repita automaticamente o pagamento.',
      action: 'check-availability',
      tone: 'deny',
    };
  }
  if (error.status === 409) {
    return {
      status: 409,
      code: error.code,
      title: 'Operação preservada',
      message: 'A operação original pode continuar em processamento.',
      recovery: 'Consulte o status e o recibo antes de qualquer nova ação.',
      action: 'check-status',
      tone: 'hold',
    };
  }
  return {
    status: error.status,
    code: error.code,
    title: 'Solicitação rejeitada',
    message: 'A solicitação foi rejeitada sem executar uma nova operação.',
    recovery: 'Revise a solicitação e preserve credenciais e evidências fora da interface.',
    action: 'none',
    tone: 'deny',
  };
}

export function presentUnavailable(fallback: string): AvalErrorPresentation {
  return {
    status: null,
    code: 'runtime_unavailable',
    title: 'Runtime indisponível',
    message: fallback,
    recovery: 'Confirme a conexão e tente carregar novamente a projeção canônica.',
    action: 'retry-read',
    tone: 'neutral',
  };
}
