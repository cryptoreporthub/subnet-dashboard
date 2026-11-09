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
  // A bearer credential with no header name in front of it. Sixteen characters
  // is the floor for an opaque token, so prose such as "bearer authentication"
  // stays readable.
  /\bbearer\s+[A-Za-z0-9._~+/=-]{16,}/gi,

  // Opaque credentials with no recognised prefix: a whole run of 32+ base64url characters with both cases and a
  // digit. A run is not matched when it sits after `+ / .` or before `+ / =`, so a piece of a base64 hash (a lockfile's
  // integrity value, which ends in `==`) is not scrubbed as a fragment of its own.
  /(?<![A-Za-z0-9_+/.-])(?=[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_+/-]))(?=[A-Za-z0-9_-]*[a-z])(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_+/=-])/g,
];

const REDACTED = "<redacted>";

const JWT_MIN_SEGMENT = 8;
const JWT_MIN_HEADER = 11;
const JWT_MAX_SEGMENT = 65_536;

function isJwtSegmentChar(char: string | undefined): boolean {
  return char !== undefined && /[A-Za-z0-9_-]/.test(char);
}

/** Index of `.` ending a segment, or null when the run is not JWT-shaped. */
function jwtDotAfterSegment(input: string, start: number, minLength: number): number | null {
  let index = start;
  const limit = Math.min(input.length, start + JWT_MAX_SEGMENT);
  while (index < limit) {
    if (input.startsWith("eyJ", index) && index > start) {
      return null;
    }
    const char = input[index];
    if (char === ".") {
      return index - start >= minLength ? index : null;
    }
    if (!isJwtSegmentChar(char)) {
      return null;
    }
    index += 1;
  }
  return null;
}

/** End index (exclusive) of a terminal base64url signature segment. */
function jwtSignatureEnd(input: string, start: number): number | null {
  let index = start;
  const limit = Math.min(input.length, start + JWT_MAX_SEGMENT);
  while (index < limit && isJwtSegmentChar(input[index])) {
    index += 1;
  }
  if (index - start < JWT_MIN_SEGMENT) {
    return null;
  }
  return index;
}

/** Linear scan for `eyJ…`.`…`.`…` triples (no lookbehind; long segments allowed). */
function scrubJwtCredentials(input: string, redactedNames: string[]): string {
  let out = "";
  let mark = 0;
  for (let index = 0; index < input.length; ) {
    if (!input.startsWith("eyJ", index)) {
      index += 1;
      continue;
    }
    const headerDot = jwtDotAfterSegment(input, index, JWT_MIN_HEADER);
    let end: number | null = null;
    if (headerDot !== null) {
      const payloadDot = jwtDotAfterSegment(input, headerDot + 1, JWT_MIN_SEGMENT);
      if (payloadDot !== null) {
        const sigEnd = jwtSignatureEnd(input, payloadDot + 1);
        if (sigEnd !== null) {
          end = sigEnd;
        }
      }
    }
    if (end !== null) {
      out += input.slice(mark, index) + REDACTED;
      mark = end;
      redactedNames.push("unlabelled-credential");
      index = end;
      continue;
    }
    index += 3;
  }
  return out + input.slice(mark);
}

/** Words that make a name a credential name. */
const CREDENTIAL_WORD =
  /token|secret|password|passwd|passphrase|api[_-]?key|apikey|private[_-]?key|client[_-]?secret|credential|authorization|bearer|access[_-]?key|session[_-]?id|pwd|(?<![a-z])pass(?![a-z])/i;

/**
 * `NAME=` / `NAME: ` / `"name": ` in front of a value. Only the name and separator
 * are matched here; the value is taken only when the name is a credential name.
 * Otherwise scanning resumes right after the separator, so an assignment nested
 * inside a value (`msg="login password=…"`, `?access_token=…`) is still examined.
 */
const ASSIGNMENT_NAME = /(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+)"?\s*[:=]\s*/g;

const ASSIGNED_VALUE =
  /"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|(?:(?:bearer|basic|token)\s+)?[^\s,;&|}]+/iy;

/** `scheme://user:password@host`: the userinfo goes, the host stays readable. */
const URL_USERINFO = /(?<![a-z0-9+.-])([a-z][a-z0-9+.-]*:\/\/)[^\s/@:]+:[^\s/@]+@/gi;

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
  // `${VAR}` and `$VAR` are references, and only upper-case names count: `$hunter2` is a value.
  if (/^(?:\$\{|\$[A-Z_])/.test(trimmed)) {
    return true;
  }
  // A generic placeholder word, with no digits: `<yourhunter2>` is a value, `<your-password>` is not.
  if (/^<(?:redacted|placeholder|example|your)[A-Za-z_\- :]*>$/i.test(trimmed)) {
    return true;
  }
  if (trimmed.toLowerCase() === "x") {
    // The one stub short enough to be mistaken for a value.
    return true;
  }
  return /^(\.\.\.|x{3,}|\*{3,}|changeme|placeholder|example|redacted|none|null|true|false)$/i.test(trimmed);
}

/**
 * Replace each credential assignment's value, scanning left to right. Credential
 * names keep their name and lose their value; every other assignment is passed over
 * at its separator, so one nested inside its value is still reached.
 */
function scrubAssignments(input: string, redactedNames: string[]): string {
  const names = new RegExp(ASSIGNMENT_NAME.source, "g");
  const values = new RegExp(ASSIGNED_VALUE.source, "iy");
  let out = "";
  let copied = 0;
  let found: RegExpExecArray | null;
  while ((found = names.exec(input)) !== null) {
    const written = found[1] ?? "";
    // A name may start with junk the old pattern left out of the label: `--password=`.
    const lead = written.match(/^[^A-Za-z0-9]*/)?.[0] ?? "";
    const label = written.slice(lead.length);
    if (!CREDENTIAL_WORD.test(label)) {
      continue;
    }
    values.lastIndex = names.lastIndex;
    const value = values.exec(input);
    if (value === null) {
      continue;
    }
    if (isPlaceholder(value[0])) {
      // A placeholder value is passed over whole, as the scrubber always did.
      names.lastIndex = values.lastIndex;
      continue;
    }
    out += input.slice(copied, found.index + lead.length) + `${label}=<redacted:${label}>`;
    copied = values.lastIndex;
    redactedNames.push(label);
    names.lastIndex = copied;
  }
  return out + input.slice(copied);
}

export function redactSecrets(input: string): RedactResult {
  const redactedNames: string[] = [];
  let text = input;

  text = scrubAssignments(text, redactedNames);

  text = text.replace(URL_USERINFO, (_match, scheme: string) => {
    redactedNames.push("url-credentials");
    return `${scheme}${REDACTED}@`;
  });

  text = scrubJwtCredentials(text, redactedNames);

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

