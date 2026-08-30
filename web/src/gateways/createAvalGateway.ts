import type { AvalGateway } from '../contracts/avalGateway.ts';
import { HttpAvalGateway } from './httpAvalGateway.ts';

export interface AvalGatewayEnvironment {
  DEV?: boolean;
  VITE_AVAL_API_BASE_URL?: string;
  VITE_AVAL_CAPTURE_ID?: string;
  VITE_AVAL_MANDATE_ID?: string;
  VITE_AVAL_USE_MOCK?: string;
}

function createDevelopmentMockGateway(): AvalGateway {
  let gatewayPromise: Promise<AvalGateway> | null = null;

  function loadGateway(): Promise<AvalGateway> {
    gatewayPromise ??= import('../fixtures/mockAvalGateway.ts')
      .then(({ createMockAvalGateway }) => createMockAvalGateway());
    return gatewayPromise;
  }

  return {
    async loadWorkspace() {
      return (await loadGateway()).loadWorkspace();
    },
    async submitTrialCommand(command) {
      return (await loadGateway()).submitTrialCommand(command);
    },
  };
}

export function createAvalGateway(environment: AvalGatewayEnvironment): AvalGateway {
  const productionBuild = import.meta.env?.PROD === true;
  if (
    !productionBuild
    && environment.DEV === true
    && environment.VITE_AVAL_USE_MOCK === 'true'
  ) {
    return createDevelopmentMockGateway();
  }
  return new HttpAvalGateway({
    baseUrl: environment.VITE_AVAL_API_BASE_URL ?? '',
    mandateId: environment.VITE_AVAL_MANDATE_ID,
    captureId: environment.VITE_AVAL_CAPTURE_ID,
  });
}
