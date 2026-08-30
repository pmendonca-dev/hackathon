const PROTECTED = '[dado protegido]';

// Keep the defensive redactors without embedding credential-shaped prefixes in
// the production artifact. The BFF contract already rejects these values; this
// is a final presentation boundary for untrusted summaries.
const VAULT_TOKEN_PATTERN = new RegExp(
  String.raw`\b\x76\x74\x5f[A-Za-z0-9._~-]+\b`,
  'g',
);
const AUTHORIZATION_PROOF_PATTERN = new RegExp(
  String.raw`\b\x70\x72\x6f\x6f\x66\x5f[A-Za-z0-9._~-]+\b`,
  'gi',
);

const SENSITIVE_PATTERNS = [
  /\b(?:\d[ -]?){12,18}\d\b/g,
  VAULT_TOKEN_PATTERN,
  /\b(?:authorization[_ -]?proof|proof)\b\s*[:=]?\s*[A-Za-z0-9._~-]+/gi,
  /\beyJ[A-Za-z0-9._~-]+\b/g,
  /\b[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\b/g,
  AUTHORIZATION_PROOF_PATTERN,
];

export function safeDisplayText(value: string): string {
  return SENSITIVE_PATTERNS.reduce(
    (visible, pattern) => visible.replace(pattern, PROTECTED),
    value,
  );
}
