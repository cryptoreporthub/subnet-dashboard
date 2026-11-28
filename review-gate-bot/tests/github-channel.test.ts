import assert from "node:assert/strict";
import test from "node:test";
import { getGitHubChannelOptions } from "@grok/agent-sdk/channels/github";

const REPO_OWNER = "cryptoreporthub";
const REPO_NAME = "subnet-dashboard";

type PaginateCall = { fn: unknown; params: Record<string, unknown> | undefined };

function mockPushContext(payload: { ref: string; deleted?: boolean }) {
  const paginateLog: PaginateCall[] = [];
  const list = () => ({});
  const octokit = {
    rest: { pulls: { list } },
    paginate: async (fn: unknown, params?: Record<string, unknown>) => {
      paginateLog.push({ fn, params });
      return [];
    },
  };
  const ctx = {
    eventName: "push" as const,
    payload,
    repository: { owner: REPO_OWNER, name: REPO_NAME },
    conversation: { number: 1522 },
    host: {
      github: { getOctokit: async () => octokit },
      kv: {
        get: async () => null,
        put: async () => {},
        delete: async () => {},
      },
      mcp: {},
    },
    github: { createCheck: async () => ({}) },
  };
  return { ctx, paginateLog: () => paginateLog, list };
}

function assertNoOpenPrListQuery(log: PaginateCall[]) {
  assert.equal(log.length, 0, "must not call paginate for open-PR list query");
}

function assertOneOpenPrListQuery(log: PaginateCall[], list: () => unknown, base: string) {
  assert.equal(log.length, 1, "branch push must issue exactly one open-PR list query");
  const call = log[0]!;
  assert.equal(call.fn, list, "open-PR list query must paginate pulls.list");
  assert.equal(call.params?.state, "open");
  assert.equal(call.params?.base, base, "base must be the branch name without refs/heads/");
  assert.equal(call.params?.owner, REPO_OWNER);
  assert.equal(call.params?.repo, REPO_NAME);
}

test("push with deleted:true issues no open-PR list query", async () => {
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  const { ctx, paginateLog } = mockPushContext({ ref: "refs/heads/main", deleted: true });
  await options!.onEvent!(ctx as never, {} as never);
  assertNoOpenPrListQuery(paginateLog());
});

test("push to refs/heads/main issues one open-PR list query", async () => {
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  const { ctx, paginateLog, list } = mockPushContext({ ref: "refs/heads/main", deleted: false });
  await options!.onEvent!(ctx as never, {} as never);
  assertOneOpenPrListQuery(paginateLog(), list, "main");
});

test("push without deleted field issues one open-PR list query", async () => {
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  const { ctx, paginateLog, list } = mockPushContext({ ref: "refs/heads/main" });
  await options!.onEvent!(ctx as never, {} as never);
  assertOneOpenPrListQuery(paginateLog(), list, "main");
});

test("push to refs/heads/feature/x issues open-PR list query with base feature/x", async () => {
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  const { ctx, paginateLog, list } = mockPushContext({ ref: "refs/heads/feature/x", deleted: false });
  await options!.onEvent!(ctx as never, {} as never);
  assertOneOpenPrListQuery(paginateLog(), list, "feature/x");
});

test("tag push issues no open-PR list query", async () => {
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  const { ctx, paginateLog } = mockPushContext({ ref: "refs/tags/v1.0.0", deleted: false });
  await options!.onEvent!(ctx as never, {} as never);
  assertNoOpenPrListQuery(paginateLog());
});
