/**
 * The holder's signing key, held by the browser and never by the server.
 *
 * AVAL's security model says spending authority is proved with the mandate holder's
 * own key: raising a limit, approving an escalation and revoking are all holder-signed
 * JWS, and deliberately *not* things an operator credential can do. A judge in a
 * browser still has to produce those signatures, and the two shortcuts — shipping a
 * server key to the page, or letting the server sign "on the holder's behalf" — would
 * each collapse that separation exactly where it is being demonstrated.
 *
 * So the browser owns a key it generated itself. The private half is created
 * `extractable: false`, which means it can be used and persisted but never serialised
 * back into bytes — not by this module, not by an extension, not by injected script.
 * There is intentionally no export function anywhere in this file.
 */

export interface HolderWallet {
  kid: string;
  privateKey: CryptoKey;
  publicJwk: JsonWebKey & { kid: string };
}

const ES256 = { name: 'ECDSA', namedCurve: 'P-256' } as const;
const SIGN_PARAMS = { name: 'ECDSA', hash: 'SHA-256' } as const;

export function base64UrlEncode(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function encodeJson(value: unknown): string {
  return base64UrlEncode(new TextEncoder().encode(JSON.stringify(value)));
}

/**
 * A fresh holder key. `extractable: false` on the private half is the point of the
 * whole module, so it is not a parameter.
 */
export async function generateHolderKeyPair(kid: string): Promise<HolderWallet> {
  const pair = await crypto.subtle.generateKey(ES256, false, ['sign', 'verify']);
  const publicJwk = (await crypto.subtle.exportKey('jwk', pair.publicKey)) as JsonWebKey;
  // The runtime matches authorities by `kid`, and JWK fields the verifier does not
  // read are noise that only invites disagreement about the key's identity.
  delete publicJwk.key_ops;
  delete publicJwk.ext;
  return {
    kid,
    privateKey: pair.privateKey,
    publicJwk: { ...publicJwk, kid },
  };
}

/**
 * Compact JWS ES256 over the claims, in the shape the Python verifier expects.
 *
 * WebCrypto returns the signature as raw r||s, which is what JWS requires. Libraries
 * that hand back a DER-wrapped signature produce tokens that verify only against
 * themselves; the 64-byte length is asserted in the tests for exactly that reason.
 */
export async function signCompactJws(
  claims: Record<string, unknown>,
  wallet: HolderWallet,
): Promise<string> {
  const signingInput = `${encodeJson({ alg: 'ES256', typ: 'JWT', kid: wallet.kid })}.${encodeJson(claims)}`;
  const signature = await crypto.subtle.sign(
    SIGN_PARAMS,
    wallet.privateKey,
    new TextEncoder().encode(signingInput),
  );
  return `${signingInput}.${base64UrlEncode(new Uint8Array(signature))}`;
}
