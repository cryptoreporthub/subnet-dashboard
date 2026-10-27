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
