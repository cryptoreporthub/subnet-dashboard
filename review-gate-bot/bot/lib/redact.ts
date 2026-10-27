/**
 * Secret scrubber. Every string that leaves the bot (GitHub comment, tool
 * result, artifact) passes through `redactSecrets` first.
 *
 * The rule is "name it, never print it": a value that looks like a credential
 * is replaced with `<redacted:NAME>` so the reader still learns which variable
 * leaked. A bare high-entropy value with no recognisable name becomes
 * `<redacted>`.
 *
 * Two holes this closes, both reported against the first version:
 *
 * 1. **All-digit values were exempt.** `DATABASE_PASSWORD=123456` came back
 *    unchanged, because every all-digit string was treated as a placeholder.
 *    A numeric password is a password. The only numeric values left alone are
 *    the ones that cannot be a credential at all — see `isPlaceholder`.
 * 2. **Only upper-case keys were matched.** A lowercase JSON key (`"token":
 *    "…"`, `password: …`) slipped past the named-assignment pattern and past
 *    every token-prefix pattern, so an opaque lowercase value survived. The key
 *    match is now case-insensitive, and the value is replaced regardless of
 *    what it looks like.
 *
 * The cost is over-redaction: a sentence like "password: rotated" loses its
 * second word. That is the right direction for a review bot whose output is
 * published.
 */

/** Values that look like credentials regardless of where they appear. */
const VALUE_PATTERNS: readonly RegExp[] = [
  // GitHub tokens: classic and fine-grained.
  /\bgh[pousr]_[A-Za-z0-9]{16,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{20,}\b/g,
  // Cursor / OpenAI / Anthropic / Slack style keys. The prefix must be followed
  // by a separator so an ordinary kebab-case identifier ("key-manager-policy")
  // is not swallowed; the value after it is long enough to be a key.
  /\b(?:sk|csk|key|cur|cr)-[A-Za-z0-9]{8,}[-_][A-Za-z0-9_-]{8,}\b/g,
  /\bxox[abposr]-[A-Za-z0-9-]{10,}\b/g,
  // Provider keys with no useful prefix structure: Anthropic and OpenAI project
  // keys, Fly.io tokens, Telegram bot tokens.
  /\bsk-[A-Za-z0-9_-]{20,}\b/g,
  /\bfo1_[A-Za-z0-9_-]{20,}\b/g,
  /\b\d{8,10}:[A-Za-z0-9_-]{35}\b/g,
  // AWS.
  /\bAKIA[0-9A-Z]{16}\b/g,
  // Google API keys.
  /\bAIza[0-9A-Za-z_-]{30,}\b/g,
  // Private key blocks, whole. A block with no END line (cut off, or the END
  // line trimmed from a log) is removed to the end of the text.
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g,
  // JWT-ish triples.
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
];

/**
 * `NAME=value` / `NAME: value` / `"name": "value"` where NAME looks like a
 * credential variable.
 *
 * Case-insensitive on the key, because `{"token": "…"}` and `password:` are as
 * much a credential as `GITHUB_TOKEN=`. The key is captured whole so the reader
 * still sees which one leaked. Kept as one pattern over `NAME<sep>VALUE`, where
 * the value is a quoted string or a bare run up to a delimiter.
 */
const NAMED_ASSIGNMENT =
  /\b([A-Za-z0-9_.-]*(?:token|secret|password|passwd|passphrase|api[_-]?key|apikey|private[_-]?key|client[_-]?secret|credential|authorization|bearer|access[_-]?key|session[_-]?id|pwd|(?<![a-z])pass(?![a-z]))[A-Za-z0-9_.-]*)"?\s*[:=]\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|(?:(?:bearer|basic|token)\s+)?[^\s,;&|}]+)/gi;

/** `scheme://user:password@host`: the userinfo goes, the host stays readable. */
const URL_USERINFO = /\b([a-z][a-z0-9+.-]*:\/\/)[^\s/@:]+:[^\s/@]+@/gi;

const REDACTED = "<redacted>";

export type RedactResult = {
  text: string;
  /** Names of the variables whose values were scrubbed, never the values. */
  redactedNames: string[];
};

/**
 * A value that carries no secret and should be left readable.
 *
 * Deliberately narrow. Template references, an already-redacted token and the
 * stub `x` stay. A short value is not a placeholder: a PIN or `DB_PASS=abc` is a credential. Everything else goes, **including
 * all digits**: a six-digit PIN or a numeric database password is a credential,
 * and the old all-digit exemption published it.
 */
function isPlaceholder(value: string): boolean {
  const trimmed = value.replace(/^["']|["']$/g, "").trim();
  if (trimmed === "") {
    return true;
  }
  if (/^(\$\{|\$[A-Z_]|<redacted|<)/.test(trimmed)) {
    return true;
  }
  if (trimmed.toLowerCase() === "x") {
    // The one stub short enough to be mistaken for a value.
    return true;
  }
  return /^(\.\.\.|x{3,}|\*{3,}|changeme|placeholder|example|redacted|none|null|true|false)$/i.test(trimmed);
}

export function redactSecrets(input: string): RedactResult {
  const redactedNames: string[] = [];
  let text = input;

  text = text.replace(NAMED_ASSIGNMENT, (match, name: string, value: string) => {
    if (isPlaceholder(value)) {
      return match;
    }
    redactedNames.push(name);
    return `${name}=<redacted:${name}>`;
  });

  text = text.replace(URL_USERINFO, (_match, scheme: string) => {
    redactedNames.push("url-credentials");
    return `${scheme}${REDACTED}@`;
  });

  for (const pattern of VALUE_PATTERNS) {
    text = text.replace(pattern, () => {
      redactedNames.push("unlabelled-credential");
      return REDACTED;
    });
  }

  return { text, redactedNames: [...new Set(redactedNames)] };
}

/** Convenience for call sites that only need the string. */
export function redacted(input: string): string {
  return redactSecrets(input).text;
}
