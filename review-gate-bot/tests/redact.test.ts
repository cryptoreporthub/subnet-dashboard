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
