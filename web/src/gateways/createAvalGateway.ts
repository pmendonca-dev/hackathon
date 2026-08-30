import type { AvalGateway } from '../contracts/avalGateway.ts';
import { createMockAvalGateway } from '../fixtures/mockAvalGateway.ts';
import { HttpAvalGateway } from './httpAvalGateway.ts';

export interface AvalGatewayEnvironment {
  DEV?: boolean;
  VITE_AVAL_API_BASE_URL?: string;
  VITE_AVAL_CAPTURE_ID?: string;
  VITE_AVAL_MANDATE_ID?: string;
  VITE_AVAL_USE_MOCK?: string;
}

export function createAvalGateway(environment: AvalGatewayEnvironment): AvalGateway {
  if (environment.DEV === true && environment.VITE_AVAL_USE_MOCK === 'true') {
    return createMockAvalGateway();
  }
  return new HttpAvalGateway({
    baseUrl: environment.VITE_AVAL_API_BASE_URL ?? '',
    mandateId: environment.VITE_AVAL_MANDATE_ID,
    captureId: environment.VITE_AVAL_CAPTURE_ID,
  });
}
