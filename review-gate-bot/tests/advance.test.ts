import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostMcpRegistry } from "@grok/agent-sdk";
import { commentTurn, pullRequestTurn, reviewEventTurn, type GateDeps } from "../bot/lib/advance.js";
import { forgetOwnIdentity } from "../bot/lib/gh.js";
import { marker } from "../bot/lib/verdicts.js";

const HEAD = "c4ae04cda0c81c4dcd0c48f9add9f46846da0cc2";
const ME = "mc-cursor-user";
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };

type Raw = {
  id: number;
  body: string;
  created_at: string;
  user: { login: string; type: string };
  performed_via_github_app: { slug: string } | null;
};

/**
 * One PR as GitHub shows it. The bot posts as `ME`, a plain user account, which
 * is what a `cursorAccount` connection does; `GET /user` is the only way to know.
 */
function world(
  options: { draft?: boolean; comments?: Raw[]; identity?: "ok" | "fails"; createFails?: boolean } = {},
) {
  const comments = [...(options.comments ?? [])];
  const posted: string[] = [];
  const state = { identityCalls: 0, identity: options.identity ?? "ok" };
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
            user: { login: ME, type: "User" },
            performed_via_github_app: null,
          });
          return { data: { id } };
        },
      },
      users: {
        getAuthenticated: async () => {
          state.identityCalls += 1;
          if (state.identity === "fails") {
            throw new Error("403 rate limited");
          }
          return { data: { login: ME } };
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
  };
  return { deps, posted, comments, state };
}

const mcPass: Raw = {
  id: 1,
  body: `${marker("mc-verdict", HEAD)}\nMC: **PASS** at \`${HEAD}\``,
  created_at: "2026-10-26T05:00:00Z",
  user: { login: ME, type: "User" },
  performed_via_github_app: null,
};

beforeEach(() => forgetOwnIdentity());

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

test("the bot's own comments do not re-enter the gate, whatever account it posts as", async () => {
  const w = world();
  await pullRequestTurn(w.deps, { action: "opened", draft: false });
  assert.equal(w.posted.length, 1);
  const own = w.comments[w.comments.length - 1];
  assert.equal(await commentTurn(w.deps, own?.user.login), false, "its own tag must not start a second turn");
  assert.equal(await commentTurn(w.deps, "some-reviewer"), true, "another author still does, while MC is missing");
});

test("a comment from the literal name 'subnet-review-gate' is just a person", async () => {
  const w = world();
  assert.equal(await commentTurn(w.deps, "subnet-review-gate"), true);
});

test("an identity lookup that fails before one has ever worked stops the gate instead of guessing", async () => {
  const w = world({ identity: "fails" });
  await assert.rejects(pullRequestTurn(w.deps, { action: "opened", draft: false }), /identity/i);
  assert.deepEqual(w.posted, [], "a gate that cannot recognise its own comments must not post");
});

test("a lookup that fails after one worked keeps the identity it had", async () => {
  const w = world({ comments: [mcPass] });
  assert.equal(await reviewEventTurn(w.deps), false, "MC PASS recognised as ours");
  w.state.identity = "fails";
  assert.equal(await reviewEventTurn(w.deps), false, "still recognised, no reset to 'MC missing'");
  assert.equal(w.posted.length <= 1, true);
});

test("a failing tag post on a pull_request event does not lose the review turn", async () => {
  const w = world({ createFails: true });
  assert.equal(await pullRequestTurn(w.deps, { action: "opened", draft: false }), true);
});
