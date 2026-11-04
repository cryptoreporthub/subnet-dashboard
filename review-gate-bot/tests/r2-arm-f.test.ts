import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import { composeVerdictBody } from "../bot/tools/post_verdict.js";
import { redactSecrets } from "../bot/lib/redact.js";
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

test("R2 arm F leaves bearer= and client_secret= in diff patches", () =>
  withArmF(() => {
    const bearerVal = "armfbearer123456789012";
    const secretVal = "armfclientsecret1234567890";
    const patch = `+def _bearer_ok(bearer=${bearerVal} | None) -> bool:\n+DEFAULT_CLIENT_SECRET=${secretVal}\n`;
    const diff = presentDiffFiles([
      { filename: "internal/auth.py", status: "modified", additions: 2, deletions: 0, patch },
    ]);
    const body = JSON.stringify(diff);
    assert.equal(body.includes(bearerVal), true);
    assert.equal(body.includes(secretVal), true);
  }));

test("R2 arm F leaves credential-shaped file text in read_repo_file windows", () =>
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
    const file = await readRepoFile(octokit, REF, HEAD, ".env", {});
    assert.equal(file.ok, true);
    if (file.ok) {
      assert.ok(file.text.includes(token));
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

test("R2 arm F windowText does not scrub private key lines (model sees raw block)", () =>
  withArmF(() => {
    const keyBody = "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu";
    const content = ["-----BEGIN RSA PRIVATE KEY-----", keyBody, "-----END RSA PRIVATE KEY-----"].join("\n");
    const window = windowText(content, {});
    assert.equal(window.text.includes(keyBody), true);
  }));
