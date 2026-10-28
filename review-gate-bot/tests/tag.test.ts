import assert from "node:assert/strict";
import test from "node:test";
import type { Octokit } from "@octokit/rest";
import type { HostKvApi } from "@grok/agent-sdk/kv";
import { readGateState, suiteKey } from "../bot/lib/gh.js";
import { prKey } from "../bot/lib/gate.js";
import { alreadyPosted, postVerdictComment, tagCursorAndDitto, tagReplit } from "../bot/lib/tag.js";
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
): Octokit & { comments: RawComment[]; created: string[]; liveHead: string; liveDraft: boolean } {
  const comments = [...initial];
  const created: string[] = [];
  let nextId = 9000;
  const octokit = {
    comments,
    created,
    /** The head `pulls.get` reports. A test moves it to simulate a push. */
    liveHead: HEAD,
    /** The draft flag `pulls.get` reports. A test flips it to simulate a PR turning draft. */
    liveDraft: false,
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
            user: { login: "simi-revision[bot]", type: "Bot" },
            performed_via_github_app: { slug: "simi-revision" },
          });
          return { data: { id: nextId } };
        },
      },
      pulls: {
        listReviews: async () => ({ data: reviews }),
        get: async () => ({ data: { head: { sha: octokit.liveHead }, draft: octokit.liveDraft } }),
      },
    },
  };
  return octokit as unknown as Octokit & { comments: RawComment[]; created: string[]; liveHead: string; liveDraft: boolean };
}

/** The three other passes at HEAD, so the gate sits on `tag_replit`. */
function passesAtHead(): { comments: RawComment[]; reviews: RawReview[]; kv: HostKvApi & { store: Map<string, unknown> } } {
  const store = kv();
  // The suite result is part of the gate input; without it `next` is run_suite.
  store.store.set(suiteKey(REF, HEAD), { state: "clean", at: 1 });
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
    user: { login: "simi-revision[bot]", type: "Bot" },
    performed_via_github_app: { slug: "simi-revision" },
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

test("tagReplit does not tag a head the PR moved off while the gate was being read", async () => {
  const { comments, reviews, kv: store } = passesAtHead();
  const octokit = fakeOctokit(comments, reviews);
  // The caller read HEAD as current; by the time the tag is about to be written
  // a push has replaced it.
  octokit.liveHead = OTHER;
  const result = await tagReplit({ octokit, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD });
  assert.equal(result.posted, false);
  assert.equal(result.reason, "gate-not-ready");
  assert.equal(octokit.created.length, 0, "Replit must not be asked to review a superseded head");
});

test("the stale-head refusal does not leave a claim that blocks the real head", async () => {
  const { comments, reviews, kv: store } = passesAtHead();
  const octokit = fakeOctokit(comments, reviews);
  octokit.liveHead = OTHER;
  await tagReplit({ octokit, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD });
  octokit.liveHead = HEAD;
  const retry = await tagReplit({ octokit, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD });
  assert.equal(retry.posted, true);
});

test("tagCursorAndDitto does not request review of a head the PR moved off", async () => {
  const octokit = fakeOctokit();
  octokit.liveHead = OTHER;
  const state = { headSha: HEAD, next: "await_cursor_ditto" } as never;
  const result = await tagCursorAndDitto({ octokit, kv: kv(), ref: REF, headSha: HEAD, state });
  assert.equal(result.posted, false);
  assert.equal(octokit.created.length, 0, "@cursor review must not land on a newer head");
});

test("a PR that turned draft after the gate was read gets no tag and no verdict", async () => {
  const octokit = fakeOctokit();
  octokit.liveDraft = true;
  const state = { headSha: HEAD, next: "await_cursor_ditto" } as never;
  const tag = await tagCursorAndDitto({ octokit, kv: kv(), ref: REF, headSha: HEAD, state });
  assert.equal(tag.posted, false);
  const verdict = await postVerdictComment({
    octokit,
    kv: kv(),
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
    body: "MC: **PASS**",
  });
  assert.equal(verdict.posted, false);
  assert.equal(octokit.created.length, 0, "a draft is never tagged, asked about or reviewed");
});

test("a verdict is not posted for a head the PR moved off between the check and the write", async () => {
  const octokit = fakeOctokit();
  octokit.liveHead = OTHER;
  const result = await postVerdictComment({
    octokit,
    kv: kv(),
    ref: REF,
    headSha: HEAD,
    currentHeadSha: HEAD,
    body: "MC: **PASS**",
  });
  assert.equal(result.posted, false);
  assert.equal(result.reason, "stale-head");
  assert.equal(octokit.created.length, 0);
});

test("a failed verdict post in one repo does not hold back the same PR number in another repo", async () => {
  const store = kv();
  const failing = fakeOctokit();
  Object.assign(failing.rest.issues, {
    createComment: async () => {
      throw new Error("GitHub 502");
    },
  });
  await assert.rejects(
    postVerdictComment({ octokit: failing, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD, body: "MC: **PASS**" }),
  );
  // The failed claim stays live: with plain get/put there is no release. The same
  // PR number and head in another repository must not queue behind it.
  const octokit = fakeOctokit();
  const other = { ...REF, owner: "someone-else" };
  const result = await postVerdictComment({
    octokit,
    kv: store,
    ref: other,
    headSha: HEAD,
    currentHeadSha: HEAD,
    body: "MC: **PASS**",
  });
  assert.equal(result.posted, true);
  assert.equal(octokit.created.length, 1);
});

test("a replit-tag record in kv alone does not count as the tag", async () => {
  const { comments, reviews, kv: store } = passesAtHead();
  store.store.set(`replit-tag:${prKey(REF)}`, { headSha: HEAD });
  const state = await readGateState({ octokit: fakeOctokit(comments, reviews), kv: store, ref: REF, headSha: HEAD });
  assert.equal(state.replitTagged, false);
  assert.equal(state.next, "tag_replit");
});

test("a failed verdict post leaves its claim live, and a repo differing only by name still posts", async () => {
  const store = kv();
  const failing = fakeOctokit();
  Object.assign(failing.rest.issues, {
    createComment: async () => {
      throw new Error("GitHub 502");
    },
  });
  await assert.rejects(
    postVerdictComment({ octokit: failing, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD, body: "MC: **PASS**" }),
  );
  // Without a compare-and-swap the failed claim is not released. Check it is really there,
  // so the test cannot pass vacuously if a release is added later.
  assert.ok(
    [...store.store.values()].some((value) => (value as { state?: unknown }).state === "claimed"),
    "the failed post must leave its claim in place",
  );
  const octokit = fakeOctokit();
  const other = { ...REF, repo: "other-dashboard" };
  const result = await postVerdictComment({
    octokit,
    kv: store,
    ref: other,
    headSha: HEAD,
    currentHeadSha: HEAD,
    body: "MC: **PASS**",
  });
  assert.equal(result.posted, true);
});

test("a Replit tag is not posted when the gate stopped being ready between the read and the post", async () => {
  // Cursor passed when the gate was read, then changed its review before the tag went up.
  const { comments, reviews, kv: store } = passesAtHead();
  const octokit = fakeOctokit(comments, reviews);
  const paginate = octokit as unknown as { paginate: (fn: unknown, ...rest: unknown[]) => Promise<unknown> };
  const listed = paginate.paginate;
  const changed = reviews.map((review) => ({ ...review, state: "CHANGES_REQUESTED" }));
  let reviewReads = 0;
  paginate.paginate = async (fn: unknown, ...rest: unknown[]) => {
    if (fn === octokit.rest.pulls.listReviews) {
      reviewReads += 1;
      return reviewReads === 1 ? reviews : changed;
    }
    return listed(fn, ...rest);
  };
  const result = await tagReplit({ octokit, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD });
  assert.equal(result.posted, false);
  assert.equal(octokit.created.length, 0, "no tag goes up for a gate that is no longer ready");
});

test("a Replit tag refused once for a gate that was not ready still posts when the gate is ready again", async () => {
  const { comments, reviews, kv: store } = passesAtHead();
  const octokit = fakeOctokit(comments, reviews);
  const paginate = octokit as unknown as { paginate: (fn: unknown, ...rest: unknown[]) => Promise<unknown> };
  const listed = paginate.paginate;
  const changed = reviews.map((review) => ({ ...review, state: "CHANGES_REQUESTED" }));
  let ready = false;
  paginate.paginate = async (fn: unknown, ...rest: unknown[]) => (fn === octokit.rest.pulls.listReviews ? (ready ? reviews : changed) : listed(fn, ...rest));
  const refused = await tagReplit({ octokit, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD });
  assert.equal(refused.posted, false);
  ready = true;
  const posted = await tagReplit({ octokit, kv: store, ref: REF, headSha: HEAD, currentHeadSha: HEAD });
  assert.equal(posted.posted, true, "a refusal does not burn the tag for the head");
  assert.equal(octokit.created.length, 1);
});
