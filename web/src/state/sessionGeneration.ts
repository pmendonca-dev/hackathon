export interface SessionGeneration {
  current(): number;
  invalidate(): number;
  isCurrent(generation: number): boolean;
}

export function createSessionGeneration(): SessionGeneration {
  let currentGeneration = 0;

  return {
    current: () => currentGeneration,
    invalidate: () => {
      currentGeneration += 1;
      return currentGeneration;
    },
    isCurrent: (generation) => generation === currentGeneration,
  };
}
