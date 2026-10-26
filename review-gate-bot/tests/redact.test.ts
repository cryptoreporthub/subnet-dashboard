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
