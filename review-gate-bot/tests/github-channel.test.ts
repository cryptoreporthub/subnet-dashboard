import assert from "node:assert/strict";
import test from "node:test";
import { getGitHubChannelOptions } from "@grok/agent-sdk/channels/github";

function mockPushContext(deleted: boolean) {
  let listCalls = 0;
  const list = () => ({});
  const octokit = {
    rest: { pulls: { list } },
    paginate: async (fn: unknown) => {
      if (fn === list) {
        listCalls += 1;
      }
      return [];
    },
  };
  const ctx = {
    eventName: "push" as const,
    payload: { ref: "refs/heads/main", deleted },
    repository: { owner: "cryptoreporthub", name: "subnet-dashboard" },
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
  return { ctx, listCalls: () => listCalls };
}

test("ditto r4478442293: a deleted-branch push does not reconcile open PRs on that base", async () => {
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  assert.equal(typeof options?.onEvent, "function");
  const { ctx, listCalls } = mockPushContext(true);
  await options!.onEvent!(ctx as never, {} as never);
  assert.equal(listCalls(), 0, "pushToBaseBranch must not run when deleted is true");
});

test("ditto r4478442293: a normal branch push still reconciles open PRs targeting that base", async () => {
  const channel = (await import("../bot/channels/github.js")).default;
  const options = getGitHubChannelOptions(channel);
  const { ctx, listCalls } = mockPushContext(false);
  await options!.onEvent!(ctx as never, {} as never);
  assert.equal(listCalls(), 1);
});
