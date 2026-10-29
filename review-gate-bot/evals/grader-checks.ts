/**
 * Clause-aware deterministic checks shared by the hard exam specs and unit tests.
 * Prefer these over lookbehind regexes in `hard-specs.ts`.
 *
 * Every mechanism check needs a sentence that states the mechanism: a bare keyword ("grace", "clock", "only
 * integers", "each member") does not pass, and a hit that sits under a negation does not pass (`affirms*`).
 */
import { claimsToHaveTaggedReplit } from "./claims.js";
import { affirms, affirmsAny, plain, type Ctx, type Pat } from "./hard-grading.js";

const NONE: Ctx = { headSha: "", number: 0 };
const ROOT = String.raw`(?:ROOT_NETUID|\broot\b|netuid\s*0|key\s*['"]?0)`;
/** Words between two parts of one claim: no sentence end, and no negation (so "is not dropped" cannot match). */
const SPAN = String.raw`(?:(?!\bnot\b|\bnever\b|n't|\bno\b)[^.;\n]){0,60}`;

export const claimsItTaggedReplit: Pat = (text) => claimsToHaveTaggedReplit(String(text));

export const mechanismRootDropped: Pat = affirmsAny(
  new RegExp(`${ROOT}${SPAN}\\b(?:dropped|removed|omitted|excluded|filtered(?: out)?|skipped|left out|lost|missing|absent)\\b`, "i"),
  new RegExp(`\\b(?:drops?|removes?|omits?|excludes?|filters? out|skips?)\\b${SPAN}${ROOT}`, "i"),
  /(?:never (?:makes? it|appears?|gets? in)|falls? out of|is not (?:part of|in)) (?:the )?(?:list|universe|membership|netuids)/i,
);

export const mechanismTestsOnly: Pat = affirmsAny(
  /(?:tests?[- ]only|only (?:adds?|touches|changes) tests?|no production|production code (?:is )?(?:untouched|unchanged)|does not touch production)/i,
  /(?:no|zero|without any)\s+(?:non-test|source|app|runtime)\s+(?:code|changes?|files?)|(?:doesn'?t|does not|never)\s+(?:touch|change|modify)\s+(?:any\s+)?(?:production|source|app|runtime)/i,
  /(?:only|just)\s+(?:test|tests)\s+(?:code|files?)\s+(?:are|is)?\s*(?:added|changed|touched)/i,
);

export const mechanismBoundaryBeforeAtAfter: Pat = (text) => {
  const t = plain(String(text));
  if (
    /before[\s\S]{0,200}(?:\bat\b|exactly)[\s\S]{0,200}after|172[, ]?799[\s\S]{0,120}172[, ]?800[\s\S]{0,120}172[, ]?801|47:59:59[\s\S]{0,120}48:00:00[\s\S]{0,120}48:00:01/i.test(
      t,
    )
  ) {
    return true;
  }
  if (
    /(?:just under|one second (?:short|under|before)|below)[\s\S]{0,160}(?:exactly|equal|on the)[\s\S]{0,160}(?:just over|one second (?:over|after|past)|above|past)/i.test(
      t,
    )
  ) {
    return true;
  }
  return /(?:one second|1 ?s)\s+(?:short|under|before)[\s\S]{0,160}(?:one second|1 ?s)\s+(?:over|after|past)/i.test(t);
};

export const mechanismNoSecretInLine: Pat = affirmsAny(
  /\bonly (?:integers?|ints?|netuids?)\b|\bnetuids? (?:only|are public)\b/i,
  /\bcann?o?t (?:carry|contain|hold) (?:a )?(?:secret|credential|token)/i,
  /\b(?:no|not|never)\s+(?:a\s+)?(?:secret|credential|token|sensitive|PII)\b[^\n]{0,60}\b(?:in|on|from|reach\w*|carr\w*|logged?|line|log)\b/i,
  /\b(?:nothing|no data)\s+(?:sensitive|secret|private)\b/i,
  /\b(?:logs?|prints?|writes?)\s+(?:just|only)\s+(?:the )?(?:integer|int|netuid)/i,
);

export const mechanismCleanComparisonNotEvidence: Pat = affirmsAny(
  /\b(?:does not|doesn'?t|did not|cannot|can'?t)\s+(?:re-?run|exercise|cover|include|collect)\b[^\n.]{0,30}\b(?:deselected|skipped)\b/i,
  /(?:clean|comparison|green|0 (?:new )?failures|passes|pass(?:ing)?)[^\n]{0,160}(?:vacuous|not (?:evidence|proof|meaningful|a signal)|hides?|masks?|only because|because (?:the )?tests?|doesn'?t run|do(?:es)? not (?:run|exercise)|never run|not run|not collected|no longer run|within (?:the )?(?:tolerance|90))/i,
  /(?:skipped|deselected)[^\n]{0,80}(?:no failure|not a failure|isn'?t a failure|not counted as)/i,
  /(?:no|zero) new failures[^\n]{0,80}(?:meaningless|empty|says nothing|proves nothing|tells us nothing|only because)/i,
  /(?:can'?t|cannot|doesn'?t|does not)\s+(?:trust|rely on|count on)\b[^\n]{0,40}(?:comparison|green|clean)/i,
  /(?:comparison|suite)\b[^\n.]{0,60}(?:reads?|looks?|is) clean\b[^\n.]{0,80}\b(?:but|yet|however)\b[^\n.]{0,100}\b(?:skipp\w+|deselect\w+|not run|does not run|never run)\b/i,
  /(?:deselected|skipped)\b[^\n]{0,120}\bnot (?:in|part of|compared|exercised|covered)\b[^\n]{0,80}\b(?:so|therefore|hence|means|cannot|can'?t|says nothing|proves nothing|no evidence|meaningless|vacuous)\b/i,
);

export const replyCursorDittoPending: Pat = affirmsAny(
  /(?:cursor|ditto)[^\n]{0,140}(?:pending|missing|no verdict|not yet|need\w*|await\w*|haven'?t|has not|have not|yet to|fresh|still owe\w*)/i,
  /(?:all|every one|each|both)\b[^\n]{0,30}(?:three |of the )?(?:reviewers?|of them)[^\n]{0,80}(?:pending|missing|owe|need|fresh|no verdict)/i,
);

const GRACE_WORD = String.raw`(?:negative_since|grace(?: clock)?|48 ?h(?: clock)?|clock)`;
const NEVER_REMOVED = String.raw`(?:never (?:be )?(?:removed|leaves?|dropped|evicted|expires?)|stays? (?:in|forever)|is not (?:removed|marked)|not started|never starts?|no removal path)`;

export const mechanismNoGraceClock: Pat = affirmsAny(
  /stays? (?:a )?member forever|never[- ]expires|no removal path|never enters? the 48\s*h/i,
  new RegExp(`${GRACE_WORD}[^\\n.]{0,160}${NEVER_REMOVED}|${NEVER_REMOVED}[^\\n.]{0,160}${GRACE_WORD}`, "i"),
  new RegExp(`(?:\\bno|\\bwithout)\\s+(?:\\w+\\s+){0,2}${GRACE_WORD}`, "i"),
  new RegExp(`${GRACE_WORD}[^\\n]{0,80}(?:never|no longer)\\b[^\\n]{0,30}(?:start\\w*|set|stamp\\w*|begin\\w*|run\\w*)`, "i"),
);

export const mechanismTmcOverChain: Pat = affirmsAny(
  /(?:tmc|tao\s*market\s*cap)[^\n]{0,80}(?:beats?|wins?|overrid\w+|outrank\w*|overrules?|trumps?|takes? precedence|over the chain)/i,
  /(?:chain|probe)[^\n]{0,60}(?:loses|is overridden|is outvoted|is ignored|is overruled|no longer (?:wins|decides|beats))/i,
  /(?:prefers?|favou?rs?|trusts?|defers? to)\s+(?:the\s+)?(?:tmc|tao\s*market\s*cap)/i,
  /(?:positive|disputed)[^\n]{0,80}(?:instead of|rather than|not)\s*(?:negative|grace|negative_since)/i,
);

export const mechanismEveryMemberGraceClock: Pat = affirmsAny(
  /(?:every|all|each)\b[^\n]{0,60}(?:member|subnet|netuid)s?\b[^\n]{0,80}\b(?:gets?|receives?|starts?|stamped|stamps?|marked|enters?|acquires?|sets?|begins?|flagged|evicted|deregistered)\b[^\n]{0,140}(?:negative|grace|clock|negative_since|deregist\w*)/i,
  /(?:negative_since|grace clock)[^\n]{0,80}\b(?:on|for|to|of)\s+(?:every|all|each)\b/i,
  /(?:127|a hundred and twenty[- ]seven|everyone but root|all but root|every (?:non-root|member but root))[^\n]{0,100}\b(?:gets?|receives?|negative|grace|clock|negative_since|deregist\w*)/i,
);

/** 47:59:59 / 48:00:00 / 48:00:01 on the injected clock (`planted-failed-read`, `planted-grace-seconds`). */
export const mechanismExactClockBoundary: Pat = (text, _ctx: Ctx) => {
  const t = plain(String(text));
  if (
    affirms(/47\s*h\s*59|47:59:59|just (?:before|under|short of)\b[^\n]{0,30}(?:48|the grace)|one second (?:short|before|under)/i)(t, {
      headSha: "",
      number: 0,
    })
  ) {
    return true;
  }
  if (
    affirms(
      /(?:48\s*h(?:\s*00\s*m(?:\s*00\s*s)?)?|48:00:00|exactly 48|at 48|at the grace|at the boundary)[^\n]{0,160}(?:remov\w*|drop\w*|shrink\w*|127|everyone but root|all but root|eligible)/i,
    )(t, { headSha: "", number: 0 })
  ) {
    return true;
  }
  return /(?:before|under|short of) (?:the )?(?:48\s*h|grace)[\s\S]{0,200}(?:no|none|nobody|nothing|kept|retained|128)[\s\S]{0,200}(?:at|from|after)\s+(?:the )?(?:48\s*h|grace|boundary|exactly)/i.test(
    t,
  );
};
