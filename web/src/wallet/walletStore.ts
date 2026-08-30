/**
 * Where the holder's key lives between page loads.
 *
 * IndexedDB stores the `CryptoKey` object itself rather than any serialisation of it,
 * which is the only way to persist a non-extractable private key: the browser keeps
 * the material, and the page keeps a handle it can sign with and cannot read. Writing
 * the key to `localStorage` would require exporting it first, and exporting it is the
 * one thing this design refuses to do.
 *
 * A wallet is per principal. Two judges sharing a laptop get two keys, and neither
 * inherits authority over the other's mandates.
 */

import { generateHolderKeyPair, type HolderWallet } from './holderKey.ts';

const DATABASE = 'aval-holder-wallet';
const STORE = 'wallets';

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transact<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return openDatabase().then(
    (database) =>
      new Promise<T>((resolve, reject) => {
        const request = run(database.transaction(STORE, mode).objectStore(STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
  );
}

export function kidFor(principalId: string): string {
  return `${principalId}_browser_k1`;
}

/**
 * The wallet for this principal, created on first use.
 *
 * Reused rather than regenerated, because the public JWK was registered on the
 * mandate as a revocation authority: a new key would leave every existing mandate
 * unrevocable from this browser.
 */
export async function loadOrCreateWallet(principalId: string): Promise<HolderWallet> {
  const key = kidFor(principalId);
  const stored = await transact<HolderWallet | undefined>('readonly', (store) => store.get(key));
  if (stored) return stored;
  const wallet = await generateHolderKeyPair(key);
  await transact('readwrite', (store) => store.put(wallet, key));
  return wallet;
}

/** Forget this browser's key. Mandates it authorised stay revocable only by whoever
 *  else holds an authority on them, so this is destructive and named to say so. */
export async function forgetWallet(principalId: string): Promise<void> {
  await transact('readwrite', (store) => store.delete(kidFor(principalId)));
}
