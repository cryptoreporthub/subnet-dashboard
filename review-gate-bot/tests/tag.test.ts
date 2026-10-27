import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { alreadyPosted, postVerdictComment, tagReplit } from "../bot/lib/tag.js";
import { marker } from "../bot/lib/verdicts.js";

const HEAD = "a".repeat(40);
const OTHER = "b".repeat(40);
const REF = { owner: "cryptoreporthub", repo: "subnet-dashboard", number: 1522 };

function kv(): HostKvApi & { store: Map<string, unknown> } {
  const store = new Map<string, unknown>();
  return {
    store,
    async get(key) {
      return store.get(key) as never;
    },
    async put(key, value) {
      store.set(key, value);
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

type RawComment = {
  id: number;
  body: string;
  created_at: string;
  user: { login: string; type: string };
  performed_via_github_app?: { slug: string } | null;
};

type RawReview = {
  id: number;
  body: string;
  state: string;
  submitted_at: string;
  commit_id: string;
  user: { login: string; type: string };
};

/**
 * A fake Octokit that answers the calls the post path makes, and records every
 * comment it creates. `comments` is mutable, so a test can check what the real
 * PR looks like after a post.
 */
function fakeOctokit(
  initial: RawComment[] = [],
  reviews: RawReview[] = [],
): Octokit & { comments: RawComment[]; created: string[] } {
  const comments = [...initial];
  const created: string[] = [];
  let nextId = 9000;
  const octokit = {
    comments,
    created,
    paginate: async (fn: unknown) => {
      if (fn === octokit.rest.pulls.listReviews) {
        return reviews;
      }
      return comments;
    },
    rest: {
      issues: {
        listComments: async () => ({ data: comments }),
        createComment: async (input: { body: string }) => {
          created.push(input.body);
          comments.push({
            id: (nextId += 1),
            body: input.body,
            created_at: "2026-10-26T06:00:00Z",
            user: { login: "subnet-review-gate[bot]", type: "Bot" },
            performed_via_github_app: { slug: "subnet-review-gate" },
          });
          return { data: { id: nextId } };
        },
      },
      pulls: {
        listReviews: async () => ({ data: reviews }),
      },
    },
  };
  return octokit as unknown as Octokit & { comments: RawComment[]; created: string[] };
}

/** The three other passes at HEAD, so the gate sits on `tag_replit`. */
function passesAtHead(): { comments: RawComment[]; reviews: RawReview[]; kv: HostKvApi } {
  const store = kv();
  // The suite result is part of the gate input; without it `next` is run_suite.
  store.store.set(`suite:${REF.number}:${HEAD}`, { state: "clean", at: 1 });
  return {
    kv: store,
    comments: [ownComment(1, `${marker("mc-verdict", HEAD)}\nMC: **PASS** at \`${HEAD}\``)],
    reviews: [
      {
        id: 10,
        body: "cursor",
        state: "APPROVED",
        submitted_at: "2026-10-26T05:10:00Z",
        commit_id: HEAD,
        user: { login: "cursor[bot]", type: "Bot" },
      },
      {
        id: 11,
        body: "ditto",
        state: "APPROVED",
        submitted_at: "2026-10-26T05:11:00Z",
        commit_id: HEAD,
        user: { login: "ditto-code[bot]", type: "Bot" },
      },
    ],
  };
}

function ownComment(id: number, body: string): RawComment {
  return {
    id,
    body,
    created_at: "2026-10-26T05:00:00Z",
    user: { login: "subnet-review-gate[bot]", type: "Bot" },
    performed_via_github_app: { slug: "subnet-review-gate" },
  };
}

// --- Finding 4: markers need the author, not just the text -----------------

test("a marker in a stranger's comment does not count as already posted", async () => {
  const octokit = fakeOctokit([
    {
      id: 1,
      body: `${marker("replit", HEAD)}\n@replit review`,
      created_at: "2026-10-26T05:00:00Z",
      user: { login: "elev8jax", type: "User" },
    },
  ]);
  assert.equal(await alreadyPosted(octokit, REF, "replit", HEAD), false);
});

test("a marker in the bot's own comment does count", async () => {
  const octokit = fakeOctokit([ownComment(1, `${marker("replit", HEAD)}\n@replit review`)]);
  assert.equal(await alreadyPosted(octokit, REF, "replit", HEAD), true);
});

test("a marker for another head is not this head", async () => {
  const octokit = fakeOctokit([ownComment(1, `${marker("replit", OTHER)}\n@replit review`)]);
  assert.equal(await alreadyPosted(octokit, REF, "replit", HEAD), false);
});

// --- Finding 5: post guard -------------------------------------------------

test("postVerdictComment posts once and reports the outcome", async () => {
  const octokit = fakeOctokit();
  const result = await postVerdictComment({
    octokit,
    kv: kv(),
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
    body: "MC: **PASS**",
  });
  assert.equal(result.posted, true);
  assert.equal(octokit.created.length, 1);
  assert.ok(octokit.created[0]?.includes(marker("mc-verdict", HEAD)));
});

test("a second post for the same head is refused, so the PR shows one verdict", async () => {
  const octokit = fakeOctokit();
  const store = kv();
  const body = "MC: **PASS**";
  await postVerdictComment({ octokit, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD, body });
  const second = await postVerdictComment({
    octokit,
    kv: kv(), // a fresh kv: GitHub must still answer "already posted"
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
    body,
  });
  assert.equal(second.posted, false);
  assert.equal(second.reason, "already-posted");
  assert.equal(octokit.created.length, 1);
});

test("a stale head is refused before anything is posted", async () => {
  const octokit = fakeOctokit();
  const result = await postVerdictComment({
    octokit,
    kv: kv(),
    ref: REF,
    headSha: OTHER,
    currentHeadSha: HEAD,
    body: "MC: **PASS**",
  });
  assert.equal(result.posted, false);
  assert.equal(result.reason, "stale-head");
  assert.equal(octokit.created.length, 0);
});

test("a verdict the gate already sees is not posted a second time", async () => {
  // The re-read immediately before the post is what catches this: the comment
  // was created by another turn after this turn read the gate.
  const octokit = fakeOctokit([ownComment(1, `${marker("mc-verdict", HEAD)}\nMC: **PASS**`)]);
  const result = await postVerdictComment({
    octokit,
    kv: kv(),
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
    body: "MC: **PASS**",
  });
  assert.equal(result.posted, false);
  assert.equal(result.reason, "already-posted");
});

// --- Finding 5: the kv-only stall -----------------------------------------

test("tagReplit reads the tag from GitHub, and a fresh kv does not cause a re-post", async () => {
  // The stall: the tag comment exists, kv has no `replit-tag:<pr>` record
  // (redeploy, or another turn posted it), and the gate stayed on tag_replit
  // forever. GitHub is the system of record.
  const { comments, reviews, kv: store } = passesAtHead();
  const octokit = fakeOctokit(
    [...comments, ownComment(2, `${marker("replit", HEAD)}\n@replit review`)],
    reviews,
  );
  const result = await tagReplit({
    octokit,
    kv: store,
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
  });
  assert.equal(result.posted, false, "a tag already on the PR is never posted again");
  assert.equal(octokit.created.length, 0);
});

test("tagReplit posts the tag when the gate allows it and GitHub has none", async () => {
  const { comments, reviews, kv: store } = passesAtHead();
  const octokit = fakeOctokit(comments, reviews);
  const result = await tagReplit({
    octokit,
    kv: store,
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
  });
  assert.equal(result.posted, true);
  assert.equal(octokit.created.length, 1);
  assert.ok(octokit.created[0]?.includes("@replit review"));
});

test("a forged replit marker does not suppress the real tag", async () => {
  const { comments, reviews, kv: store } = passesAtHead();
  const octokit = fakeOctokit(
    [
      ...comments,
      {
        id: 99,
        body: `${marker("replit", HEAD)}\n@replit review`,
        created_at: "2026-10-26T05:30:00Z",
        user: { login: "elev8jax", type: "User" },
      },
    ],
    reviews,
  );
  const result = await tagReplit({
    octokit,
    kv: store,
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
  });
  assert.equal(result.posted, true, "a stranger's marker cannot stand in for the gate's tag");
  assert.equal(octokit.created.length, 1);
});
