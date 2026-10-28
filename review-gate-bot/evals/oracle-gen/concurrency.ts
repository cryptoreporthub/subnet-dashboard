// Runs one copy of review-gate-bot/bot/lib (a "process") against a fake GitHub and a plain get/put kv.
// Driven by gen.py (see README.md). usage: tsx concurrency.ts <libDirA> <libDirB>   (two separate module graphs = two processes)
import { pathToFileURL } from "node:url";

type Comment = { id: number; body: string; created_at: string; updated_at: string; user: { login: string; type: string }; performed_via_github_app: null };

const HEAD = "a".repeat(40);
const MOVED = "b".repeat(40);

function world() {
  const comments: Comment[] = [];
  let head = HEAD;
  let id = 1;
  const octokit: any = {
    paginate: async (fn: any) => {
      if (fn === octokit.rest.issues.listComments) return comments.map((c) => ({ ...c }));
      return [];
    },
    rest: {
      issues: {
        listComments: async () => ({ data: [] }),
        createComment: async (p: { body: string }) => {
          await new Promise((r) => setTimeout(r, 5));
          const c: Comment = { id: id++, body: p.body, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), user: { login: "simi-revision[bot]", type: "Bot" }, performed_via_github_app: null };
          comments.push(c);
          return { data: { id: c.id } };
        },
      },
      pulls: { get: async () => ({ data: { head: { sha: head }, draft: false, number: 1 } }), listFiles: async () => ({ data: [] }) },
    },
  };
  return { comments, octokit, setHead: (h: string) => (head = h), getHead: () => head };
}

function kv(slowFirstGetMs = 0) {
  const m = new Map<string, unknown>();
  let gets = 0;
  return {
    get: async (k: string) => {
      const snapshot = m.get(k);
      if (gets++ === 0 && slowFirstGetMs > 0) await new Promise((r) => setTimeout(r, slowFirstGetMs));
      return snapshot;
    },
    put: async (k: string, v: unknown) => void m.set(k, v),
    delete: async (k: string) => void m.delete(k),
  } as any;
}

async function load(dir: string) {
  return (await import(pathToFileURL(`${dir}/tag.ts`).href)) as typeof import("../../bot/lib/tag.js");
}

const ref = { owner: "o", repo: "r", number: 1 };

export async function run(dirA: string, dirB: string) {
  const A = await load(dirA);
  const B = await load(dirB);

  // 1. the same verdict delivered to two processes, both before the marker write.
  const w1 = world();
  const kvA = kv(0), kvB = kv(40);
  const [ra, rb] = await Promise.all([
    A.postVerdictComment({ octokit: w1.octokit, kv: kvA, ref, headSha: HEAD, currentHeadSha: HEAD, body: "MC: **PASS** at head" }),
    (async () => { await new Promise((r) => setTimeout(r, 2)); return B.postVerdictComment({ octokit: w1.octokit, kv: kvB, ref, headSha: HEAD, currentHeadSha: HEAD, body: "MC: **MODIFY** at head" }); })(),
  ]);
  const verdictComments = w1.comments.filter((c) => c.body.includes("mc-verdict:")).map((c) => (/\*\*(PASS|MODIFY|FAIL)\*\*/.exec(c.body) ?? [])[1]);

  // 2. a head push lands between the gate read and the tag write.
  const w2 = world();
  const state = { headSha: HEAD, mc: "PASS", cursor: "missing", ditto: "missing", replit: "missing", suite: "missing", replitTagged: false, next: "await_cursor_ditto" } as any;
  const origList = w2.octokit.paginate;
  let first = true;
  w2.octokit.paginate = async (fn: any) => {
    const out = await origList(fn);
    if (first) { first = false; w2.setHead(MOVED); } // the push lands while the tag is being decided
    return out;
  };
  const tag = await A.tagCursorAndDitto({ octokit: w2.octokit, kv: kv(0), ref, headSha: HEAD, state });
  const tagged = w2.comments.map((c) => /Head under review: `([0-9a-f]{40})`/.exec(c.body)?.[1]);

  return {
    duplicateVerdict: { results: [ra, rb].map((r) => ({ posted: r.posted, reason: r.reason })), commentsOnPr: verdictComments.length, verdictsInOrder: verdictComments, gateReadsLatest: verdictComments.at(-1) ?? null },
    headPushDuringTag: { prHeadAtWrite: w2.getHead(), outcome: { posted: tag.posted, reason: tag.reason }, tagCommentsFor: tagged.map((h) => (h === HEAD ? "old-head" : h === MOVED ? "new-head" : "none")) },
  };
}

if (process.argv[1]?.endsWith("concurrency.ts")) {
  const [a, b] = process.argv.slice(2);
  run(a!, b!).then((r) => console.log(JSON.stringify(r)));
}
