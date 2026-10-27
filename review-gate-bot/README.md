# subnet-review-gate

The Mission Control PR review gate for `cryptoreporthub/subnet-dashboard`, as a
versioned Cursor Agent SDK project.

It reviews a pull request adversarially, decides the gate order in plain
TypeScript, and posts the `@cursor` / `@ditto` / `@replit` review requests
itself. **Nobody tags by hand.** Verdicts post live from day one; there is no
shadow mode.

## What it does

- On **PR opened, new head (`synchronize`), and review/comment events**: posts
  the bot's verdict for that head, then exactly **one** comment tagging
  `@cursor review` and `@ditto review`.
- When MC, Cursor and Ditto have all PASSed **the same head** and the full-suite
  comparison is clean, posts `@replit review` **once** for that head.
- Then nudges Replit's MCP `ask_question` once per head, if the connector is
  reachable. **The ask is not a review.** `ask_question` asks an existing Replit
  app a question; it does not start a review run. So the gate advances only on
  Replit's own posted verdict on the PR, never on a successful ask. A failed ask
  is retried on later events and reported loudly once it is persistent.
- Refuses a second review or a second tag for the same head, including on
  duplicate webhooks and replays.

### What it can read

Four read-only tools let the bot see the change it reviews: `check_gate_state`
(the PR's head, files and gate), `get_pr_diff`, `list_repo_files` and
`read_repo_file`. Each is pinned to the PR its session is
bound to, applies secret redaction, and caps its output. The built-in shell and
file tools stay off (`tools: []`), so the bot reads code and cannot run it.
Whatever it concludes about behaviour is labelled inferred.

### How a verdict is counted

| Reviewer | Counts when |
| --- | --- |
| MC | this bot's own `mc-verdict` marker comment, author **and** SHA checked |
| Cursor | `cursor[bot]` review or first-line token |
| Ditto | App-attributed comment, or `ditto-code[bot]` review |
| Replit | owner-account comment naming Replit, with **no** App attribution |

A verdict is an explicit `PASS` / `MODIFY` / `FAIL` token on the **first line**
of a comment, or a formal review state. There is no prose fallback:
"not approved", "not a PASS" and "no PASS yet" are all rejected, and a token
buried in a paragraph is not a verdict.

Every post is guarded per `(PR number, head SHA)`, **at most once and best
effort**. GitHub is the system of record: each comment carries a marker naming
its slot and SHA, and the bot reads the PR back before posting. A marker only
counts when this bot's own identity posted it, so a stranger cannot suppress the
tag or forge a verdict by copying the text. A replay cannot double-post, and
neither can overlapping events inside one process (callers for a key run one at a
time). A genuine simultaneous race between two processes can, because the hosted
kv has no compare-and-swap; the gate reads the latest marker, so two different
verdicts racing across processes resolve to the later one.

## Drafts

A draft PR is never tagged, never asked about, and never reviewed. The guard
sits in one function (`gateActions`) that every hook calls, so `onComment` and
`onEvent` refuse drafts the same way `onPullRequest` always did.

## What this bot will never do

There is no tool for any of these, anywhere in the project, on purpose:

- merge, close, or label a pull request
- deploy, restart, scale, or roll back anything
- set, read, or print a secret value
- push code, to any branch
- post on a pull request other than the one its session is bound to
- treat a comment from the repo account or any bot as Joshua's GO

A guardrail by absence beats a guardrail by prompt.

## Prerequisites

- **Node 22.13 or newer.** The SDK requires it; Bun is not supported.
- A Cursor account signed in on the machine that runs or deploys this agent (model turns, and the Replit connector).
- GitHub access to `cryptoreporthub/subnet-dashboard`.

## Install

```bash
cd review-gate-bot
npm install
```

## Check it

```bash
npm run check     # tsc --noEmit
npm test          # gate, suite, redaction, verdict, lock and fixture tests (no model)
npm run validate  # agent-sdk validate --dir .
```

`npm test` needs no model and no network. It covers the gate order, the
flake-aware suite diff, secret redaction, Ditto-vs-Joshua attribution, the
per-head lock, and that every eval fixture agrees with `lib/gate.ts`. It also
runs the **end-to-end parser path**: raw GitHub comment/review JSON →
normalizers → `collectPinnedVerdicts` → `computeGate`, which is the only route
that proves MC's own verdict is read back.

The full suite gate reads JUnit from the workflow's own artifact:

| What | Where |
| --- | --- |
| JUnit XML | `pytest-junit` artifact of the `full-suite-junit.yml` run for the **exact** SHA |
| Known flakes | committed `known-flakes.txt` (never a tool argument) |
| Zero testcases | a failed comparison, never a clean one |
| Carry-over | only when every changed file is prose/an image **and** the source SHA has a recorded clean run |

> **Dependency, outside this folder.** `.github/workflows/full-suite-junit.yml`
> (PR #1525) runs the whole suite and uploads the `pytest-junit` artifact. It is
> report only and gates nothing. `ci-smoke.yml` runs a subset, so it is not used.
> Until `main` carries that workflow, a comparison refuses with `base-no-run`,
> which is the intended failure: an absent report must never read as a clean suite.

## Run it locally

```bash
npx agent-sdk login            # only if `agent-sdk whoami` says you are signed out
npm run dev                    # agent-sdk dev --dir .  (playground + HTTP)
```

The playground is at `http://127.0.0.1:3000/playground`.

To drive it from real GitHub deliveries without a public webhook, replay a PR
against the running `npm run dev` (it reads the PR with `gh api`; pull access is
enough). `--dry-run` prints the payloads and posts nothing. `--fixtures-dir`
writes them out, `fixtures/github` being the SDK's convention (the folder is
created on first use, and is not the eval snapshots under `evals/fixtures/`):

```bash
npx agent-sdk github replay cryptoreporthub/subnet-dashboard#1515 --dir . --dry-run \
  --events '*' --fixtures-dir fixtures/github
```

## Evals

```bash
npx agent-sdk eval --dir . --list          # the 7 cases
npx agent-sdk eval --dir . --tag smoke     # run them
npx agent-sdk eval --dir . --json --no-stream --junit reports/evals.xml
```

Seven cases, from real history: `pr-1515-grace-overflow`,
`pr-1515-unprompted`, `pr-1519-docs-head`, `pr-1486-elev8jax`,
`go-forgery`, `gate-order`, `secret-echo`. Each pins a PR snapshot and a gate
state under `evals/fixtures/`, so a run does not read a PR as it looks today.

The two `pr-1515` cases replay the PR at the head MC passed, before the overflow
was found. The first names the file and the setting; the second names nothing
but the PR. Neither names a value (`tests/fixtures.test.ts` keeps it so): a case
that hands over `1e308` measures reading, not review. A kept change to the
instructions needs an eval that would have failed before it, so the cases are
run by hand (`--tag`) after a change, not in CI.

A finding that rules out a PASS (rows that never expire, an overflow, a cycle
or later row that can abort or inherit bad state) is declared in `post_verdict`'s
`blocking` list. The tool refuses a PASS while the list is not empty, so the
verdict is MODIFY or FAIL whatever the finding's severity.

Tool writes are stubbed in an eval session (`ctx.session.purpose === "eval"`),
so `calledTool` still sees the decision and nothing is posted.

## Identity

The bot posts as its own GitHub App, **Simi-Revision** (slug `simi-revision`,
App ID 5495359, login `simi-revision[bot]`), installed on
`cryptoreporthub/subnet-dashboard` only. It holds checks, pull requests and
issues as read/write and code, Actions and statuses as read. It has no merge,
admin or secrets permission.

A marker comment counts as the gate's own only when its author is
`simi-revision[bot]`. A `[bot]` login cannot be registered by a person, so a
copied marker from anyone else is ignored.

The Grokbot App posts MC verdicts as `simibot[bot]`. Its MC verdict counts only
when GitHub attributes the comment to App ID **5501340** (slug `simibot`). A
comment named `simibot[bot]` with any other App ID, or with no App attribution,
is ignored, and so is anything simibot posts into the Cursor, Ditto or Replit
slots. Reviews from simibot never count. The App ID was read from the REST API
on PR #1522's simibot comments.

**Remaining limit.** MC and Claude still post from `cryptoreporthub`, the owner's
account, so their verdict comments are only as trustworthy as that account.
Giving each of them its own App closes it.

### The `review-gate` check

For every non-draft head the bot opens a `review-gate` check run on that commit:
green only when the gate is `mergeable`, red on a FAIL, and `action_required` while
anything is still pending. GitHub counts `neutral` and `skipped` as passing for a
required check, so a waiting head never uses either. A head that moves while the
check is posted is concluded `cancelled` as superseded, never reported green. The
check reports and gates nothing by itself; making it a required check is a
branch-protection decision for Joshua.

## Secrets

Only **names** ever appear in this repo. Joshua sets the values.

| Name | What it is |
| --- | --- |
| `GITHUB_APP_ID` | the App's ID, `5495359` |
| `GITHUB_APP_PRIVATE_KEY` | the App's private key (PEM) |
| `GITHUB_WEBHOOK_SECRET` | the secret the App signs webhook deliveries with |
| `GITHUB_APP_INSTALLATION_ID` | the installation, `175819081`. Tools run outside a webhook delivery, and the SDK reads the installation from this name there. Not secret, but only a deployment secret can carry it. |

Set each without putting the value on the command line, so it stays out of your
shell history and off any transcript:

```bash
printf %s "$VALUE" | npx agent-sdk secret set subnet-review-gate GITHUB_APP_PRIVATE_KEY
```

`npx agent-sdk secret list subnet-review-gate` prints names only. Never pass
`--from-argv`. Local runs can use `GITHUB_TOKEN` or `gh auth login` instead.

`bot/channels/github.ts` names the three credentials, and `bot/agent.ts`
declares all four in `secretNames`, so `deploy` warns about any that is unset.

**Webhook.** A GitHub App delivers events by webhook, not through the Cursor
account. After the first deploy, point the App's webhook URL at the deployment's
`/v1/channels/github` route and set the same secret on both sides. The App's
webhook is off until then, so the bot hears nothing.

## Deploy

Prerequisites: your Cursor team must be on **Privacy Mode**. Managed hosting is
not available under Privacy Mode (Legacy) — `deploy` refuses.

```bash
npx agent-sdk validate --dir .
npx agent-sdk deploy --dir . --dry-run     # reads only; stop at the first change
npx agent-sdk deploy --dir .               # run this in your own terminal
```

The first deploy prints an **alias token one time**. Save it in a password
manager; it is not shown again. Do not paste it into a chat or a file.

Then verify the surface:

```bash
npx agent-sdk info --dir . --json --fields slug,name
npx agent-sdk deployment get subnet-review-gate --json --fields status,lastError
```

## Going live

The bot is live as soon as the deployment reports `status: running` and GitHub
deliveries arrive. There is no trial phase to wait out: the first new head it
sees gets a real verdict and a real `@cursor` + `@ditto` tag.

1. Confirm `npx agent-sdk deployment get subnet-review-gate --json --fields status`
   shows a running status.
2. Open or push to a PR in `cryptoreporthub/subnet-dashboard`. Its first
   head gets one verdict comment and one `@cursor review` + `@ditto review`
   comment.
3. Watch the first few hours:

   ```bash
   npx agent-sdk logs --slug subnet-review-gate --once
   ```

4. To pause it without deleting anything:

   ```bash
   npx agent-sdk deployment stop subnet-review-gate
   npx agent-sdk deployment start subnet-review-gate
   ```

To roll out a change: push a commit to this folder, `npx agent-sdk deploy --dir .`
again. Sessions, `ctx.host.kv` and artifacts survive a redeploy; a fresh slug
does not.

## Configuration

| Where | What |
| --- | --- |
| `bot/agent.ts` | the pinned `model` (`grok-4.5`, `effort=high`, `fast=true`), `hosting.egressDomains` (`api.github.com`, `mcp.replit.com`, and the Actions artifact storage hosts `*.blob.core.windows.net` and `*.actions.githubusercontent.com`), `hosting.secretNames`, `concurrency.maxRunningTurns`. `local.sandbox` is deliberately absent. |
| `bot/channels/github.ts` | the repo, the trigger actions, `webhookEvents`, and the automatic tagging |
| `bot/instructions.md` | the adversarial review policy and the hard nevers |
| `bot/lib/gate.ts` | the gate order and the delivery decision (`gateActions`: draft guard, tag, ask). The only place that decides `next`. |
| `bot/lib/verdicts.ts` | how each verdict is attributed, and the first-line-only token rule |
| `bot/lib/repo.ts` | the read-only diff, file and listing helpers behind the read tools |
| `bot/lib/runner.ts` | JUnit from the runner artifact for an exact SHA |
| `known-flakes.txt` | the committed flake list `compare_suite_runs` reads |
| `bot/skills/` | on-demand procedures: adversarial review, owner rules, settled check, outside commenters |
| `bot/host-connections/replit.ts` | the conditional Replit MCP connection |

### How a verdict is attributed

Ditto posts from Joshua's own account through the `ditto-code` GitHub App, so
`user.login` alone cannot separate them. **Measured on PR #1515:**

- timeline comments carry `performed_via_github_app.slug === "ditto-code"`;
- the reviews API carries **no** `performed_via_github_app` key at all, so a
  review is attributed Ditto by `user.login === "ditto-code[bot]"`.

A comment with any App attribution is never Joshua's GO, whichever account it
came from. Only Joshua acting as himself is, and no code path here can merge or
deploy on any comment.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `eval` fails with `could not resolve Cursor event authentication` | not signed in. `agent-sdk login`, or set `CURSOR_API_KEY`. |
| `deploy` refuses under Privacy Mode (Legacy) | switch the team to Privacy Mode, or ask a team admin |
| No tag appears on a new head | `check_gate_state` returned `blocked`, or the head moved between the read and the post. The bot re-reads on the next event. |
| Replit is never asked | the Cursor account has no `Replit` MCP connector. The tag still posts; the ask stays with MC. |
