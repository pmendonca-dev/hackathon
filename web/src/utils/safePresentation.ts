const PROTECTED = '[dado protegido]';

const SENSITIVE_PATTERNS = [
  /\b(?:\d[ -]?){12,18}\d\b/g,
  /\bvt_[A-Za-z0-9._~-]+\b/g,
  /\b(?:authorization[_ -]?proof|proof)\b\s*[:=]?\s*[A-Za-z0-9._~-]+/gi,
  /\beyJ[A-Za-z0-9._~-]+\b/g,
  /\b[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\b/g,
  /\bproof_[A-Za-z0-9._~-]+\b/gi,
];

export function safeDisplayText(value: string): string {
  return SENSITIVE_PATTERNS.reduce(
    (visible, pattern) => visible.replace(pattern, PROTECTED),
    value,
  );
}
