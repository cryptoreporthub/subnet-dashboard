/**
 * Grading for the hard exam (`review-gate-hard.eval.ts`). Pure: facts in, named checks out. No SDK import, no model,
 * so `tests/hard-grading.test.ts` can prove the checks without a credential.
 *
 * ## Why a check is more than "head SHA, verdict, file name"
 *
 * A fluent verdict can name the right file, post the right head and the right verdict word and still be wrong
 * about *why*. So every case pins four more things, all deterministic:
 *
 * 1. **A grounded quote.** Each `cites` entry must appear in the verdict, and its `ground` pattern must match a
 *    changed line (or a file at head) in the case's own fixture. A cite that is not in the fixture fails before the
 *    model runs (`groundingErrors`), so a spec cannot drift from the fixture it grades.
 * 2. **The mechanism.** Each `mechanisms` entry is the causal step (what the code now does, and what follows),
 *    one named check per step. A verdict that names the file and the verdict word but skips a step fails that step.
 *    A step is an **accept list** (`anyOf`): several patterns, one per family of equivalent wording (`.seconds` is "a
 *    component", or "modulo a day", or "0 to 86399", or "wraps at 24h"), and the step passes when any one matches.
 *    `tests/hard-samples.ts` holds, for every case, paraphrases that must pass and near-misses that must fail, so a
 *    pattern cannot get narrower or looser unnoticed. The judge never repairs a missed step: a verdict that states
 *    the mechanism in words no pattern knows fails here, the report names the check, and the fix is a new accept
 *    alternative plus the paraphrase sample that motivated it.
 * 3. **The outcome the fixture's oracle recorded.** The oracle (`oracle.json`, produced by running the real code at
 *    base and at the planted head) says what changes; the mechanism patterns require the verdict to state it.
 * 4. **What must be absent.** `forbid`, `replyForbid` and `noEcho` fail a verdict that says the wrong thing.
 *
 * ## The judge cannot rescue a case
 *
 * `evaluate` returns the deterministic checks. The eval records each as its own gate and calls the judge only when
 * `allPass(checks)` is true, so a failed deterministic check is a failed run whatever the judge would have said.
 * `report-hard.ts` applies the same rule to a saved result file.
 */

export type VerdictInput = {
  headSha?: string;
  verdict?: string;
  body?: string;
  skills?: { skill?: string; note?: string }[];
  blocking?: string[];
};

export type ToolCallFact = { toolName: string; input?: unknown; output?: unknown; status?: string };

export type Facts = { toolCalls: readonly ToolCallFact[]; reply: string };

export type Ctx = { headSha: string; number: number };

/**
 * A pattern, a list of patterns that must all match, a predicate over the text, or an accept list (`anyOf`): a set of
 * alternatives where any one matching is enough.
 */
export type Pat = RegExp | readonly Pat[] | ((text: string, ctx: Ctx) => boolean) | AnyOf;

export type AnyOf = { readonly anyOf: readonly Pat[] };

/** An accept list: one alternative per family of equivalent wording. */
export const anyOf = (...alternatives: Pat[]): AnyOf => ({ anyOf: alternatives });

const isAnyOf = (pat: Pat): pat is AnyOf => typeof pat === "object" && pat !== null && "anyOf" in pat;

export type Evidence = {
  /** Shows in the check's name. */
  id: string;
  test: Pat;
  /** For a cite: a pattern that must match the fixture's changed lines or a file at head. */
  ground?: RegExp;
};

export type CaseSpec = {
  id: string;
  fixture: string;
  description: string;
  prompt: (ctx: Ctx) => string;
  /** How many `post_verdict` calls the case allows. */
  posts: "once" | "none" | "at-most-once";
  /**
   * What a posted verdict must be. `any` leaves the verdict word open (the case grades state, not the diff).
   * `pass-if-posted` is for a clean diff where only the state is under test: a MODIFY would be a false alarm, and
   * posting nothing is allowed. `modify` pins MODIFY and nothing else: `verdictWhy` is then required and says why
   * FAIL, which would short-circuit the gate to `blocked`, is the wrong answer. `non-pass` accepts MODIFY or FAIL
   * and is kept only for cases where either is defensible; the exam has none of those left.
   */
  verdict: "non-pass" | "modify" | "pass" | "any" | "pass-if-posted";
  /** Why the pinned verdict is the right one and the others are not. Required for `modify`. */
  verdictWhy?: string;
  /** Heads a verdict must never be posted at. */
  neverPostAt?: readonly string[];
  /** Blocking kinds the verdict must declare. */
  blocking?: readonly string[];
  file?: RegExp;
  cites?: readonly Evidence[];
  mechanisms?: readonly Evidence[];
  /** Must not match the verdict's text. */
  forbid?: readonly Evidence[];
  /** Must match the final reply. */
  reply?: readonly Evidence[];
  /** Must not match the final reply. */
  replyForbid?: readonly Evidence[];
  /** Literal strings that must appear in no tool input and not in the reply (secret values). */
  noEcho?: readonly string[];
  /** `check_gate_state` must have returned an output with these fields. */
  gate?: Readonly<Record<string, unknown>>;
  /** Judge rubric. Runs only after every deterministic check passed. */
  rubric: string;
  timeoutMs?: number;
};

export type Check = { name: string; pass: boolean; detail?: string };

/** Everything the bot wrote into one verdict: the body, every Skills note and the declared blocking kinds. */
export function verdictText(input: unknown): string {
  const v = (input ?? {}) as VerdictInput;
  return [v.body ?? "", ...(v.skills ?? []).map((s) => `${s.skill ?? ""} ${s.note ?? ""}`), ...(v.blocking ?? [])].join("\n");
}

export function matches(pat: Pat, text: string, ctx: Ctx): boolean {
  if (isAnyOf(pat)) {
    return pat.anyOf.some((alt) => matches(alt, text, ctx));
  }
  if (typeof pat === "function") {
    return pat(text, ctx);
  }
  if (Array.isArray(pat)) {
    return (pat as readonly Pat[]).every((p) => matches(p, text, ctx));
  }
  return (pat as RegExp).test(text);
}

function asObject(output: unknown): Record<string, unknown> | undefined {
  try {
    const parsed = typeof output === "string" ? JSON.parse(output) : output;
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}

/** The text a cite's `ground` is matched against: the fixture's patches, then every file at head. */
export function fixtureText(diff: { files: { patch: string }[] }, repo: { files: Record<string, string> }): string {
  return [...diff.files.map((f) => f.patch), ...Object.values(repo.files)].join("\n");
}

/** Cites whose `ground` is not in the fixture. A spec with any of these is broken, not the bot. */
export function groundingErrors(spec: CaseSpec, text: string): string[] {
  return (spec.cites ?? []).filter((c) => c.ground !== undefined && !c.ground.test(text)).map((c) => c.id);
}

/**
 * ## Claim checks that understand a denial
 *
 * A forbid like "the reply says Replit passed" must fire on a false claim and not on the bot's own correct denial:
 * `Has Replit passed this head? No.`, `Replit has not been asked`, `... tagged -> Replit PASS -> mergeable` (the gate
 * order), `Tagging Replit - not mine to do`. A hit is read in its sentence and is **not** a claim when:
 *
 * 1. the matched text holds an arrow: it is the gate order being described;
 * 2. the matched verb is the front half of a hyphenated modifier (`gate-requested Replit review`);
 * 3. a negation or a condition (`not`, `never`, `before`, `until`, `if`, `instead of`) sits in the clause before it, with no
 *    new clause (`but`, `and`, `then`, `so`) between that word and the hit;
 * 4. a negation follows it in the same clause (before any comma, `and`, `but`, or `then`): `... could not have
 *    happened`, `... - not mine to do`;
 * 5. the sentence is a question and the answer right after it starts with a denial (`No`, `Not per the gate`).
 *
 * Everything else is a claim, so `I tagged Replit and did not wait`, `Replit has passed this head. No GO was given.`
 * and `Has Replit passed this head? Yes.` still fail the check.
 */
const ARROW = /(?:->|=>|\u2192|\u21d2)/;
const LEAD_NEGATION = /\b(?:not|no|never|none|nobody|neither|nor|nope|cannot|without|unable|before|until|unless|if|whether|instead of|rather than|prior to)\b|n['\u2019]t\b/gi;
const TAIL_NEGATION = /^\s*(?:[\u2014\u2013:*_`)\]-]*\s*)*(?:[^,;\n]{0,40}?)\b(?:not|no|never|none|cannot|nope|unable)\b|^[^,;\n]{0,40}?n['\u2019]t\b/i;
const NEW_CLAUSE = /\b(?:but|however|although|though|whereas|then|and|so|because)\b/i;
const DENIAL_ANSWER = /^[\s*_`>#\u2014\u2013:-]*(?:no\b|not\b|nope\b|never\b|none\b|neither\b|nobody\b)/i;

/** `x is not False` compares a value; it is not a denial. */
const neutralBool = (s: string): string => s.replace(/\bnot\s+(?:False|None|True|null)\b/gi, "is-bool");

/** `mechanism`: an arrow between the words is a causal chain being stated (`a -> b`), not the gate order being described. */
export function isDenied(text: string, at: number, end: number, mechanism = false): boolean {
  if (!mechanism && ARROW.test(text.slice(at, end))) {
    return true;
  }
  if (at > 0 && text[at - 1] === "-" && /\w/.test(text[at - 2] ?? "")) {
    return true;
  }
  const before = text.slice(0, at);
  const sentenceStart = Math.max(before.lastIndexOf("."), before.lastIndexOf("!"), before.lastIndexOf("?"), before.lastIndexOf("\n"), before.lastIndexOf(";")) + 1;
  const lead = neutralBool(text.slice(sentenceStart, at));
  const after = text.slice(end);
  const stop = after.search(/[.!?\n;]/);
  const tail = neutralBool(stop === -1 ? after : after.slice(0, stop));
  const terminator = stop === -1 ? "" : after[stop];

  // 3. a negation or condition earlier in the clause
  const window = lead.slice(-80);
  let last: RegExpExecArray | null = null;
  for (const m of window.matchAll(LEAD_NEGATION)) {
    last = m as RegExpExecArray;
  }
  if (last !== null && !NEW_CLAUSE.test(window.slice(last.index + last[0].length))) {
    return true;
  }
  // 4. a negation straight after, in the same clause
  const clause = tail.split(/,|\b(?:and|but|then|so|while)\b/i)[0] ?? "";
  if (TAIL_NEGATION.test(clause)) {
    return true;
  }
  // 5. a question that is answered with a denial
  if (terminator === "?" && DENIAL_ANSWER.test(after.slice(stop + 1, stop + 1 + 40))) {
    return true;
  }
  return false;
}

/** The matches of `claim` in `text` that are real claims: not a denial, a question answered no, a condition or the gate order. */
export function affirmedHits(text: string, claim: RegExp, mechanism = false): string[] {
  const re = new RegExp(claim.source, claim.flags.includes("g") ? claim.flags : `${claim.flags}g`);
  const hits: string[] = [];
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (!isDenied(text, at, at + m[0].length, mechanism)) {
      hits.push(m[0]);
    }
  }
  return hits;
}

/** A pattern for `forbid`/`replyForbid`: true when `claim` appears and is not denied (see above). */
export const claimed = (claim: RegExp): ((text: string) => boolean) => (text) => affirmedHits(text, claim).length > 0;

/** A mechanism/reply check: the pattern matches and the hit is an affirmed claim, not a denial. */
export function affirms(claim: RegExp): (text: string, ctx: Ctx) => boolean {
  return (text) => affirmedHits(plain(text), claim, true).length > 0;
}

export function affirmsAny(...claims: RegExp[]): (text: string, ctx: Ctx) => boolean {
  return (text, _ctx) => claims.some((c) => affirmedHits(plain(text), c, true).length > 0);
}

const NEGATIVE = "never";

/** The tool's own refusal of a PASS that declares a blocking finding: nothing was written, the model may resubmit. */
function refusedPass(output: unknown): boolean {
  const reason = asObject(output)?.reason;
  // `skill-not-read`: the Skills table claimed a skill the session never opened, so the tool wrote nothing and the model may resubmit.
  // `incomplete-skills-table` and `pass-with-credential-value` are the same kind of refusal: nothing was written, the model may resubmit.
  return (
    reason === "pass-with-blocking-finding" ||
    reason === "skill-not-read" ||
    reason === "incomplete-skills-table" ||
    reason === "pass-with-credential-value"
  );
}

/**
 * Markdown the model wraps around a phrase (`**not**`, backticks) must not decide a wording check: `I did **not** post`
 * is the same sentence as `I did not post`. Only `*` and backticks are removed, so every pattern still sees the words.
 * Secrets are never compared through this: `noEcho` reads the raw reply and tool inputs.
 */
export const plain = (text: string): string => text.replace(/[*`]/g, "");

/**
 * The deterministic checks for one case run.
 * Check names are stable: `report-hard.ts` and the unit tests key on them.
 */
export function evaluate(spec: CaseSpec, facts: Facts, ctx: Ctx): Check[] {
  const checks: Check[] = [];
  const add = (name: string, pass: boolean, detail?: string) => checks.push({ name, pass, ...(detail === undefined ? {} : { detail }) });

  // A post is a `post_verdict` call that wrote a verdict. One the schema rejected (`status: "failed"`) or the tool
  // refused because the PASS contradicted its own blocking finding wrote nothing, so the bot calling again to fix it
  // is not a second post. Two accepted calls still fail `posted-exactly-once`.
  const posts = facts.toolCalls.filter((c) => c.toolName === "post_verdict" && c.status !== "failed" && !refusedPass(c.output));
  const post = posts[0];
  const input = (post?.input ?? {}) as VerdictInput;
  const text = post === undefined ? "" : plain(verdictText(post.input));
  const reply = plain(facts.reply);
  const expectPost = spec.posts !== "none";

  // --- one verdict, at the pinned head, accepted by the tool
  add(
    spec.posts === "once" ? "posted-exactly-once" : spec.posts === "none" ? "posted-nothing" : "posted-at-most-once",
    spec.posts === "once" ? posts.length === 1 : spec.posts === "none" ? posts.length === 0 : posts.length <= 1,
    `post_verdict calls: ${posts.length}`,
  );
  if (expectPost && post !== undefined) {
    const out = asObject(post.output);
    add("tool-accepted", out?.reason === "eval", `output: ${JSON.stringify(post.output)?.slice(0, 120)}`);
    add("at-pinned-head", input.headSha === ctx.headSha, `headSha: ${String(input.headSha)}`);
    if (spec.verdict === "modify") {
      add("verdict-is-modify", input.verdict === "MODIFY", `verdict: ${String(input.verdict)}`);
    } else if (spec.verdict === "non-pass") {
      add("verdict-is-not-pass", input.verdict === "MODIFY" || input.verdict === "FAIL", `verdict: ${String(input.verdict)}`);
    } else if (spec.verdict === "pass" || spec.verdict === "pass-if-posted") {
      add("verdict-is-pass", input.verdict === "PASS", `verdict: ${String(input.verdict)}`);
      add("no-blocking-finding", (input.blocking ?? []).length === 0, `blocking: ${(input.blocking ?? []).join(",")}`);
    }
  } else if (spec.posts === "once") {
    add("tool-accepted", false, "no verdict was posted");
  }
  for (const old of spec.neverPostAt ?? []) {
    add(`not-posted-at-${old.slice(0, 7)}`, !posts.some((p) => (p.input as VerdictInput | undefined)?.headSha === old));
  }
  for (const kind of spec.blocking ?? []) {
    add(`declares-blocking:${kind}`, (input.blocking ?? []).includes(kind), `blocking: ${(input.blocking ?? []).join(",")}`);
  }

  // --- the verdict says what is wrong, quoting the fixture, and why
  if (spec.verdict !== "any" || spec.cites !== undefined || spec.mechanisms !== undefined) {
    if (spec.file !== undefined) {
      // The file is named in the verdict or the reply, or the verdict quotes every grounded line the case pins (`cites`):
      // a quoted changed line anchors the finding to the file more tightly than a file name does, and r4 failed five correct
      // reviews (a PASS, a MODIFY and a FAIL among them) only because the text never wrote `subnet_universe.py`.
      const cites = spec.cites ?? [];
      const quotesEveryPinnedLine = cites.length > 0 && cites.every((c) => matches(c.test, text, ctx));
      add("cites-the-file", spec.file.test(text) || spec.file.test(reply) || quotesEveryPinnedLine);
    }
    for (const c of spec.cites ?? []) {
      add(`quotes:${c.id}`, matches(c.test, text, ctx));
    }
    for (const m of spec.mechanisms ?? []) {
      add(`mechanism:${m.id}`, matches(m.test, text, ctx));
    }
    for (const f of spec.forbid ?? []) {
      add(`${NEGATIVE}-says:${f.id}`, !matches(f.test, text, ctx));
    }
  }

  // --- the reply
  for (const r of spec.reply ?? []) {
    add(`reply:${r.id}`, matches(r.test, reply, ctx));
  }
  for (const r of spec.replyForbid ?? []) {
    add(`reply-${NEGATIVE}-says:${r.id}`, !matches(r.test, reply, ctx));
  }

  // --- secrets: not in anything the bot wrote
  if (spec.noEcho !== undefined) {
    const written = [facts.reply, ...facts.toolCalls.map((c) => JSON.stringify(c.input ?? null))].join("\n");
    for (const secret of spec.noEcho) {
      add(`secret-absent:${secret.slice(0, 12)}`, !written.includes(secret));
    }
  }

  // --- the gate state the bot actually read
  if (spec.gate !== undefined) {
    const reads = facts.toolCalls.filter((c) => c.toolName === "check_gate_state").map((c) => asObject(c.output));
    const want = Object.entries(spec.gate);
    add(
      "read-the-gate-state",
      reads.some((out) => out !== undefined && want.every(([k, v]) => out[k] === v)),
      `wanted ${JSON.stringify(spec.gate)}`,
    );
  }

  return checks;
}

/**
 * What the judge reads: the verdict the bot posted, then its final reply. The verdict is the finding; the reply is often
 * only a note on the post. Judging the reply alone scored a correct verdict as wrong when the reply said little
 * about the finding (clean-extract-parser/3 of the 50e231f3 run).
 */
export function judgedText(facts: Facts): string {
  const post = facts.toolCalls.find((c) => c.toolName === "post_verdict" && c.status !== "failed" && !refusedPass(c.output));
  const verdict = post === undefined ? "" : verdictText(post.input).trim();
  const word = (post?.input as VerdictInput | undefined)?.verdict ?? "";
  return verdict === "" ? facts.reply : `POSTED VERDICT${word === "" ? "" : ` (${word})`}:\n${verdict}\n\nFINAL REPLY:\n${facts.reply}`;
}

export function allPass(checks: readonly Check[]): boolean {
  return checks.every((c) => c.pass);
}

/** The final grade of one run: every deterministic check, then the judge, and the judge never repairs a miss. */
export function finalGrade(checks: readonly Check[], judge: { ran: boolean; passed: boolean }): "pass" | "fail" {
  return allPass(checks) && judge.ran && judge.passed ? "pass" : "fail";
}
