import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import { composeVerdictBody } from "../bot/tools/post_verdict.js";
import { redactSecrets } from "../bot/lib/redact.js";
import { r2MethodArmFromEnv, methodArmFromEnv } from "../bot/lib/method-variants.js";
import { scrubModelRepoReads } from "../bot/lib/model-read-redaction.js";
import { presentDiffFiles, readRepoFile, windowText } from "../bot/lib/repo.js";

const REF = { owner: "o", repo: "r", number: 7 };
const HEAD = "a".repeat(40);
const b64 = (text: string): string => Buffer.from(text, "utf8").toString("base64");

function withArmF<T>(fn: () => T | Promise<T>): Promise<T> {
  const prev = process.env.R2_METHOD_ARM;
  process.env.R2_METHOD_ARM = "F";
  return Promise.resolve(fn()).finally(() => {
    if (prev === undefined) {
      delete process.env.R2_METHOD_ARM;
    } else {
      process.env.R2_METHOD_ARM = prev;
    }
  });
}

test("r2MethodArmFromEnv maps F honestly; methodArmFromEnv stays prompt-neutral (A)", () =>
  withArmF(() => {
    assert.equal(r2MethodArmFromEnv(), "F");
    assert.equal(methodArmFromEnv(), "A");
  }));

test("scrubModelRepoReads: live session always scrubs even when arm F", () =>
  withArmF(() => {
    assert.equal(scrubModelRepoReads("live"), true);
  }));

test("R2 arm F eval leaves bearer= and client_secret= in diff patches", () =>
  withArmF(() => {
    const bearerVal = "armfbearer123456789012";
    const secretVal = "armfclientsecret1234567890";
    const patch = `+def _bearer_ok(bearer=${bearerVal} | None) -> bool:\n+DEFAULT_CLIENT_SECRET=${secretVal}\n`;
    const diff = presentDiffFiles(
      [{ filename: "internal/auth.py", status: "modified", additions: 2, deletions: 0, patch }],
      { purpose: "eval" },
    );
    const body = JSON.stringify(diff);
    assert.equal(body.includes(bearerVal), true);
    assert.equal(body.includes(secretVal), true);
  }));

test("R2 arm F live still redacts bearer= and client_secret= in diff patches", () =>
  withArmF(() => {
    const bearerVal = "livebearer1234567890123";
    const secretVal = "liveclientsecret1234567890";
    const patch = `+bearer=${bearerVal}\n+client_secret=${secretVal}\n`;
    const diff = presentDiffFiles(
      [{ filename: "internal/auth.py", status: "modified", additions: 2, deletions: 0, patch }],
      { purpose: "live" },
    );
    const body = JSON.stringify(diff);
    assert.equal(body.includes(bearerVal), false);
    assert.equal(body.includes(secretVal), false);
  }));

test("R2 arm F eval leaves credential-shaped file text in read_repo_file windows", () =>
  withArmF(async () => {
    const token = "ghp_" + "ArmFReadRepoFile0123456789";
    const octokit = {
      rest: {
        repos: {
          getContent: async () => ({
            data: { type: "file", encoding: "base64", size: 40, content: b64(`GITHUB_TOKEN=${token}`) },
          }),
        },
      },
    } as unknown as Octokit;
    const file = await readRepoFile(octokit, REF, HEAD, ".env", { purpose: "eval" });
    assert.equal(file.ok, true);
    if (file.ok) {
      assert.ok(file.text.includes(token));
    }
  }));

test("R2 arm F live still redacts credential-shaped file text in read_repo_file", () =>
  withArmF(async () => {
    const token = "ghp_" + "ArmFLiveReadRepo0123456789";
    const octokit = {
      rest: {
        repos: {
          getContent: async () => ({
            data: { type: "file", encoding: "base64", size: 40, content: b64(`GITHUB_TOKEN=${token}`) },
          }),
        },
      },
    } as unknown as Octokit;
    const file = await readRepoFile(octokit, REF, HEAD, ".env", { purpose: "live" });
    assert.equal(file.ok, true);
    if (file.ok) {
      assert.equal(file.text.includes(token), false);
    }
  }));

test("R2 arm F still scrubs verdict bodies before GitHub post path", () =>
  withArmF(() => {
    const token = "ghp_" + "ArmFPostMustRedact012345678";
    const { text } = redactSecrets(
      composeVerdictBody({
        verdict: "MODIFY",
        headSha: HEAD,
        body: `Leaked ${token} in review`,
        skills: [{ skill: "settled-check", used: true, note: "ok" }],
      }),
    );
    assert.equal(text.includes(token), false);
  }));

test("R2 arm F eval windowText does not scrub private key lines (model sees raw block)", () =>
  withArmF(() => {
    const keyBody = "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu";
    const content = ["-----BEGIN RSA PRIVATE KEY-----", keyBody, "-----END RSA PRIVATE KEY-----"].join("\n");
    const window = windowText(content, { purpose: "eval" });
    assert.equal(window.text.includes(keyBody), true);
  }));

test("R2 arm F live windowText still scrubs private key lines", () =>
  withArmF(() => {
    const keyBody = "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu";
    const content = ["-----BEGIN RSA PRIVATE KEY-----", keyBody, "-----END RSA PRIVATE KEY-----"].join("\n");
    const window = windowText(content, { purpose: "live" });
    assert.equal(window.text.includes(keyBody), false);
  }));
