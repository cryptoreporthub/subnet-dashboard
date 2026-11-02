import assert from "node:assert/strict";
import test from "node:test";
import { redactSecrets } from "../bot/lib/redact.js";

test("a named credential keeps the name and loses the value", () => {
  const { text, redactedNames } = redactSecrets("GITHUB_TOKEN=ghp_abc123def456ghi789jkl012");
  assert.equal(text.includes("ghp_abc123"), false);
  assert.equal(text.includes("GITHUB_TOKEN=<redacted:GITHUB_TOKEN>"), true);
  assert.deepEqual(redactedNames, ["GITHUB_TOKEN"]);
});

test("JSON-shaped credentials are redacted too", () => {
  const { text } = redactSecrets('{"RESOLVER_API_KEY": "sk-live-abcdefghijklmnop"}');
  assert.equal(text.includes("sk-live"), false);
  assert.equal(text.includes("RESOLVER_API_KEY=<redacted:RESOLVER_API_KEY>"), true);
});

test("an unlabelled GitHub token is redacted without a name", () => {
  const { text, redactedNames } = redactSecrets("the key is ghp_aaaaaaaaaaaaaaaaaaaa here");
  assert.equal(text.includes("ghp_aaaa"), false);
  assert.equal(text.includes("<redacted>"), true);
  assert.deepEqual(redactedNames, ["unlabelled-credential"]);
});

test("a private key block is removed whole", () => {
  const block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----";
  const { text } = redactSecrets(`before ${block} after`);
  assert.equal(text.includes("MIIEow"), false);
  assert.equal(text.includes("after"), true);
});

test("placeholders and template references are left alone", () => {
  const source = 'TOKEN=${GITHUB_TOKEN}\nSECRET=""\nAPI_KEY=x\nPASSWORD=changeme';
  assert.equal(redactSecrets(source).text, source);
});

test("a variable name with no secret-looking word is untouched", () => {
  const source = "PORT=8080\nLOG_LEVEL=debug";
  assert.equal(redactSecrets(source).text, source);
});

test("a body naming the variable but not the value passes unchanged", () => {
  const body = "The diff prints `GITHUB_TOKEN` to stdout. Value not reproduced here.";
  const { text, redactedNames } = redactSecrets(body);
  assert.equal(text, body);
  assert.deepEqual(redactedNames, []);
});

// --- Finding 6: all-digit values are credentials too ----------------------

test("an all-digit password is redacted, not exempted as a placeholder", () => {
  // The reported hole: every all-digit value was treated as a placeholder, so
  // this came back unchanged.
  const { text, redactedNames } = redactSecrets("DATABASE_PASSWORD=123456");
  assert.equal(text.includes("123456"), false);
  assert.equal(text.includes("DATABASE_PASSWORD=<redacted:DATABASE_PASSWORD>"), true);
  assert.deepEqual(redactedNames, ["DATABASE_PASSWORD"]);
});

test("a lowercase numeric password and a numeric client secret are redacted", () => {
  assert.equal(redactSecrets('{"password": "8675309"}').text.includes("8675309"), false);
  assert.equal(redactSecrets('{"client_secret": "987654321"}').text.includes("987654321"), false);
  assert.equal(redactSecrets("API_KEY=1234567890").text.includes("1234567890"), false);
});

test("only the explicit stub `x` is left readable; a short real credential is redacted", () => {
  assert.equal(redactSecrets("API_KEY=x").text, "API_KEY=x");
  const short: [source: string, secret: string][] = [
    ["DB_PASS=abc", "abc"],
    ["PASSWORD=ab", "ab"],
    ["pwd=1234", "1234"],
    ["SECRET=a1", "a1"],
    ["token: abc", "abc"],
  ];
  for (const [source, secret] of short) {
    const { text, redactedNames } = redactSecrets(source);
    assert.equal(text.split(/[=:]/).slice(1).join("").includes(secret), false, source);
    assert.equal(redactedNames.length, 1, source);
  }
});

test("a numeric value that cannot be a credential is still left readable", () => {
  // The narrow exception: below the four-character floor there is nothing to
  // protect, so a stub like `x` or `1` is not turned into noise.
  const source = "API_KEY=x";
  assert.equal(redactSecrets(source).text, source);
});

// --- Finding 6: lowercase credential keys --------------------------------

test("a lowercase JSON token key is matched case-insensitively", () => {
  const { text, redactedNames } = redactSecrets('{"token": "opaquevalue1234"}');
  assert.equal(text.includes("opaquevalue1234"), false);
  assert.equal(text.includes("<redacted:token>"), true);
  assert.deepEqual(redactedNames, ["token"]);
});

test("a bare lowercase key=value pair is matched too", () => {
  const source = "password: hunter2hunter2";
  const { text } = redactSecrets(source);
  assert.equal(text.includes("hunter2hunter2"), false);
});

test("mixed-case credential keys are matched", () => {
  const { text } = redactSecrets('"Api_Key": "abcdef123456"');
  assert.equal(text.includes("abcdef123456"), false);
});

test("a long kebab-case identifier is not swallowed as a credential", () => {
  // The old `key-`/`cur-`/`cr-` pattern redacted long kebab-case names. A
  // single-segment word like this must survive so the review stays readable.
  const source = "see the key-manager documentation for details";
  assert.equal(redactSecrets(source).text, source);
});

test("a real key-shaped value after a `key-` prefix is still redacted", () => {
  const { text } = redactSecrets("key-abcdefghijklmnop_qrstuvwx0123");
  assert.equal(text.includes("abcdefghijklmnop"), false);
});

// --- Second review: credential shapes that survived -----------------------

test("a bearer token loses its value, not just the word Bearer", () => {
  const { text } = redactSecrets("Authorization: Bearer ya29.a0AfH6SMBabcdefghijklmnopqrstuvwxyz0123");
  assert.equal(text.includes("ya29"), false);
});

test("a standalone bearer token is redacted even with no header name", () => {
  const { text, redactedNames } = redactSecrets("the call sent Bearer Q7mK4pV9xR2nL6sT8wY3 upstream");
  assert.equal(text.includes("Q7mK4pV9xR2nL6sT8wY3"), false);
  assert.deepEqual(redactedNames, ["unlabelled-credential"]);
});

test("prose after the word bearer stays readable", () => {
  const source = "see the Bearer authentication tokens section and basic implementation-notes";
  assert.equal(redactSecrets(source).text, source);
});

test("credentials inside a URL are removed", () => {
  const { text } = redactSecrets("DATABASE at postgres://admin:hunter22@db.internal:5432/app is down");
  assert.equal(text.includes("hunter22"), false);
  assert.equal(text.includes("db.internal"), true, "the host stays; only the userinfo goes");
});

test("provider key shapes are removed without a variable name", () => {
  for (const secret of [
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx",
    "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz012345",
    "fo1_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw0",
  ]) {
    assert.equal(redactSecrets(`found ${secret} in the log`).text.includes(secret), false, secret);
  }
});

test("pass and pwd count as credential names, but bypass and passed do not", () => {
  assert.equal(redactSecrets("DB_PASS=hunter22").text.includes("hunter22"), false);
  assert.equal(redactSecrets("MY_PWD=hunter22").text.includes("hunter22"), false);
  const prose = "BYPASS_CACHE=enabled\nTESTS_PASSED=forty-two";
  assert.equal(redactSecrets(prose).text, prose);
});

test("a private key with no END line is removed to the end of the text", () => {
  const { text } = redactSecrets("log:\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\nmore");
  assert.equal(text.includes("b3BlbnNz"), false);
});

// Timing guards: the scrubber is synchronous, so a slow pattern stalls the whole bot. The
// limits are generous; the fixed patterns finish in milliseconds.
function timed(input: string): { text: string; ms: number } {
  const started = performance.now();
  const { text } = redactSecrets(input);
  return { text, ms: performance.now() - started };
}

test("a 100 KB run of name characters with no keyword scrubs in under a second", () => {
  const { ms } = timed("a.b-".repeat(25_000));
  assert.ok(ms < 1000, `took ${Math.round(ms)} ms`);
});

test("a 100 KB run of keyword-dense name characters scrubs in under a second", () => {
  const { ms } = timed("token".repeat(20_000));
  assert.ok(ms < 1000, `took ${Math.round(ms)} ms`);
});

test("a credential name longer than any fixed bound is still redacted", () => {
  const { text, redactedNames } = redactSecrets(`${"X".repeat(120)}_TOKEN=plainvalue9Z8Y7X6W`);
  assert.equal(text.includes("plainvalue9Z8Y7X6W"), false);
  assert.equal(redactedNames.length, 1);
});

// A credential assignment nested inside another value is still a credential.
test("a password nested inside a JSON string is redacted", () => {
  const { text } = redactSecrets('{"msg":"login password=hunter2 failed"}');
  assert.equal(text.includes("hunter2"), false);
});

test("a password inside a command-line flag is redacted", () => {
  const { text } = redactSecrets("cmd=--password=hunter2");
  assert.equal(text.includes("hunter2"), false);
});

test("an access token in a query string is redacted", () => {
  const { text } = redactSecrets("redirect=https://h/cb?access_token=abc123xyz789");
  assert.equal(text.includes("abc123xyz789"), false);
});

test("a credential at the end of an assignment chain is redacted", () => {
  const { text } = redactSecrets("a=b=token=zzzzzzzz");
  assert.equal(text.includes("zzzzzzzz"), false);
});

test("a 100 KB run of JWT-shaped segments scrubs in under a second", () => {
  const { ms } = timed("eyJaaaaaaaa-".repeat(9_000));
  assert.ok(ms < 1000, `took ${Math.round(ms)} ms`);
});

test("a credential after a placeholder-valued credential is still redacted", () => {
  // Found by a differential fuzz against the 44ce7ea scrubber: the placeholder `$VAR` must be
  // passed over whole, or the scan re-reads its quoted text and misses `api_key`.
  const { text } = redactSecrets('?TOKEN="$VAR?TOKEN":"basic??api_key":"SECRET2947x4Z');
  assert.equal(text.includes("SECRET2947x4Z"), false);
});

test("a 1 MB run of JWT-shaped segments joined by dashes scrubs in under half a second", () => {
  const { ms } = timed("eyJaaaaaaaa-".repeat(90_000));
  assert.ok(ms < 500, `took ${Math.round(ms)} ms`);
});

// A deliberate choice, pinned: a JWT glued to the word before it by a dash or an underscore is
// not matched by the JWT rule (the lookbehind excludes both, which keeps the scan linear). A JWT
// after a space, `=` or `:` is matched.
test("a JWT glued by a dash or underscore is not matched by the JWT rule, and a spaced one is", () => {
  const jwt = "eyJhbGciOiJIUzI1NiJ9." + "a".repeat(80) + "." + "b".repeat(43);
  assert.equal(redactSecrets(`x-${jwt}`).text.includes(jwt), true, "dash-glued: the JWT rule does not match");
  assert.equal(redactSecrets(`x_${jwt}`).text.includes(jwt), true, "underscore-glued: the JWT rule does not match");
  assert.equal(redactSecrets(`x ${jwt}`).text.includes(jwt), false, "space-separated: matched");
});

test("an angle-bracketed credential is redacted; only generic placeholder words are passed over", () => {
  const leaked = redactSecrets("PASSWORD=<hunter2>").text;
  assert.equal(leaked.includes("hunter2"), false, `leaked: ${leaked}`);
  assert.equal(redactSecrets("PASSWORD=<placeholder>").text.includes("<placeholder>"), true);
});

test("a dollar-prefixed credential is redacted: only ${VAR} and $VAR references are placeholders", () => {
  assert.equal(redactSecrets("PASSWORD=$hunter2").text.includes("hunter2"), false);
});

test("an angle-bracketed value with a digit is a credential, not a placeholder word", () => {
  assert.equal(redactSecrets("PASSWORD=<yourhunter2>").text.includes("yourhunter2"), false);
});

test("a standalone opaque credential with no known prefix is redacted", () => {
  const token = "Q7mK4pV9xR2nL6sT8wY3aB5cD7eF9gH1";
  assert.equal(redactSecrets(`session=${token}`).text.includes(token), false, "an assigned value");
  assert.equal(redactSecrets(`the value was ${token} in the log`).text.includes(token), false, "a bare value in prose");
});

test("ordinary words and kebab-case identifiers stay readable", () => {
  const prose = "the verdict-gate-review-bot-deterministic-check is green and the Replit-Ditto-Cursor loop ran";
  assert.equal(redactSecrets(prose).text, prose);
});

test("the opaque-credential rule scrubs a megabyte of identifier characters quickly", () => {
  const run = "A".repeat(1_000_000);
  const started = performance.now();
  redactSecrets(run);
  assert.ok(performance.now() - started < 500, "the rule must not backtrack across a long run");
});
