/**
 * Secret scrubber. Every string that leaves the bot (GitHub comment, tool
 * result, artifact) passes through `redactSecrets` first.
 *
 * The rule is "name it, never print it": a value that looks like a credential
 * is replaced with `<redacted:NAME>` so the reader still learns which variable
 * leaked. A bare high-entropy value with no recognisable name becomes
 * `<redacted>`.
 */

/** Values that look like credentials regardless of where they appear. */
const VALUE_PATTERNS: readonly RegExp[] = [
  // GitHub tokens: classic and fine-grained.
  /\bgh[pousr]_[A-Za-z0-9]{16,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{20,}\b/g,
  // Cursor / OpenAI / Anthropic / Slack style keys.
  /\b(?:sk|csk|key|cur|cr)-[A-Za-z0-9_-]{16,}\b/g,
  /\bxox[abposr]-[A-Za-z0-9-]{10,}\b/g,
  // AWS.
  /\bAKIA[0-9A-Z]{16}\b/g,
  // Google API keys.
  /\bAIza[0-9A-Za-z_-]{30,}\b/g,
  // Private key blocks, whole.
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
  // JWT-ish triples.
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
];

/**
 * `NAME=value` / `NAME: value` / `"NAME": "value"` where NAME looks like a
 * credential variable. Keeps the name, drops the value.
 */
const NAMED_ASSIGNMENT =
  /\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|PRIVATE_KEY|CLIENT_SECRET|CREDENTIALS?)[A-Z0-9_]*)"?\s*[:=]\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s,;&|}]+)/g;

const REDACTED = "<redacted>";

export type RedactResult = {
  text: string;
  /** Names of the variables whose values were scrubbed, never the values. */
  redactedNames: string[];
};

function isPlaceholder(value: string): boolean {
  const trimmed = value.replace(/^["']|["']$/g, "").trim();
  if (trimmed === "") {
    return true;
  }
  // A template reference, an already-redacted token, or an obvious stub.
  if (/^(\$\{|\$[A-Z_]|<redacted|<)/.test(trimmed)) {
    return true;
  }
  if (trimmed.length < 4) {
    // No real credential is under four characters; these are stubs like `x`.
    return true;
  }
  return /^(\.\.\.|x{3,}|\*{3,}|changeme|placeholder|example|redacted|none|null|true|false|-?\d+)$/i.test(
    trimmed,
  );
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
