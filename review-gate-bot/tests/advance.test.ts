import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import { commentTurn, pullRequestTurn, reviewEventTurn, type GateDeps } from "../bot/lib/advance.js";
import { marker } from "../bot/lib/verdicts.js";

const HEAD = "c4ae04cda0c81c4dcd0c48f9add9f46846da0cc2";
const ME = "simi-revision[bot]";
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };

type Raw = {
  id: number;
  body: string;
  created_at: string;
  user: { login: string; type: string };
  performed_via_github_app: { slug: string } | null;
};

type CheckCall = { name: string; sha: string; conclusion?: string };

/** One PR as GitHub shows it. The bot posts as its own App, `ME`. */
function world(
  options: { draft?: boolean; comments?: Raw[]; createFails?: boolean; headMovesTo?: string; checkFails?: boolean } = {},
) {
  const comments = [...(options.comments ?? [])];
  const posted: string[] = [];
  const checks: CheckCall[] = [];
  const listComments = () => {};
  const listReviews = () => {};
  const octokit = {
    paginate: async (fn: unknown) => (fn === listComments ? comments : []),
    rest: {
      pulls: {
        get: async () => ({ data: { head: { sha: HEAD }, draft: options.draft ?? false } }),
        listReviews,
      },
      issues: {
        listComments,
        createComment: async ({ body }: { body: string }) => {
          if (options.createFails === true) {
            throw new Error("github 502");
          }
          const id = 1000 + posted.length;
          posted.push(body);
          comments.push({
            id,
            body,
            created_at: "2026-10-26T06:00:00Z",
            user: { login: ME, type: "Bot" },
            performed_via_github_app: null,
          });
          return { data: { id } };
        },
      },
    },
  } as unknown as Octokit;

  const store = new Map<string, unknown>();
  const deps: GateDeps = {
    octokit,
    kv: {
      get: async (key) => store.get(key) as never,
      put: async (key, value) => {
        store.set(key, value);
      },
      delete: async (key) => {
        store.delete(key);
      },
    },
    mcp: { names: () => [], listTools: async () => [], callTool: async () => ({ isError: false, content: [] }) } as unknown as HostMcpRegistry,
    ref: REF,
    createCheck: async (input) => {
      if (options.checkFails === true) {
        throw new Error("github 403");
      }
      const call: CheckCall = { name: input.name, sha: input.sha };
      checks.push(call);
      return {
        update: async () => {},
        conclude: async ({ conclusion }) => {
          call.conclusion = conclusion;
        },
      };
    },
  };
  return { deps, posted, comments, checks };
}

const mcPass: Raw = {
  id: 1,
  body: `${marker("mc-verdict", HEAD)}\nMC: **PASS** at \`${HEAD}\``,
  created_at: "2026-10-26T05:00:00Z",
  user: { login: ME, type: "Bot" },
  performed_via_github_app: null,
};

test("a PR that is a draft right now starts no turn and posts nothing, whatever the payload says", async () => {
  const w = world({ draft: true });
  assert.equal(await pullRequestTurn(w.deps, { action: "synchronize", draft: false }), false);
  assert.deepEqual(w.posted, []);
});

test("a reopened PR whose head already has an MC verdict starts no second review", async () => {
  const w = world({ comments: [mcPass] });
  assert.equal(await pullRequestTurn(w.deps, { action: "reopened", draft: false }), false);
});

test("a PR with no MC verdict yet starts a review turn and tags Cursor and Ditto once", async () => {
  const w = world();
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
  assert.equal(await pullRequestTurn(w.deps, { action: "synchronize", draft: false }), true);
  assert.equal(w.posted.length, 1);
  assert.ok(w.posted[0]?.includes("@cursor review"));
});

test("the bot's own comments do not re-enter the gate", async () => {
  const w = world();
  await pullRequestTurn(w.deps, { action: "opened", draft: false });
  assert.equal(w.posted.length, 1);
  const own = w.comments[w.comments.length - 1];
  assert.equal(await commentTurn(w.deps, own?.user.login), false, "its own tag must not start a second turn");
  assert.equal(await commentTurn(w.deps, "some-reviewer"), true, "another author still does, while MC is missing");
});

test("a comment from the bare name 'simi-revision' is just a person", async () => {
  const w = world();
  assert.equal(await commentTurn(w.deps, "simi-revision"), true);
});

test("a comment from the owner's account is never the bot's, even one that carries a marker", async () => {
  const w = world();
  await pullRequestTurn(w.deps, { action: "opened", draft: false });
  const ownTag = w.comments[w.comments.length - 1];
  assert.equal(await commentTurn(w.deps, "cryptoreporthub"), true, "the owner account is shared, so it still runs the gate");
});

test("a failing tag post on a pull_request event does not lose the review turn", async () => {
  const w = world({ createFails: true });
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
});

// --- The review-gate check run ------------------------------------------------

test("a head still waiting on reviewers gets a neutral review-gate check, never a green one", async () => {
  const w = world();
  await pullRequestTurn(w.deps, { action: "opened", draft: false });
  assert.deepEqual(w.checks, [{ name: "review-gate", sha: HEAD, conclusion: "neutral" }]);
});

test("a FAIL anywhere at the head posts a failing review-gate check", async () => {
  const w = world({ comments: [{ ...mcPass, body: `${marker("mc-verdict", HEAD)}\nMC: **FAIL** at \`${HEAD}\`` }] });
  await reviewEventTurn(w.deps);
  assert.equal(w.checks[0]?.conclusion, "failure");
});

test("the same gate state at the same head posts its check once, not once per webhook", async () => {
  const w = world();
  await reviewEventTurn(w.deps);
  await reviewEventTurn(w.deps);
  await reviewEventTurn(w.deps);
  assert.equal(w.checks.length, 1);
});

test("a draft gets no check at all", async () => {
  const w = world({ draft: true });
  await reviewEventTurn(w.deps);
  assert.deepEqual(w.checks, []);
});

test("a failing check post does not lose the review turn or the tags", async () => {
  const w = world({ checkFails: true });
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
  assert.equal(w.posted.length, 1, "the Cursor and Ditto tag still went out");
});
