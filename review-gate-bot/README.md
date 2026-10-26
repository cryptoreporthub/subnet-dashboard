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
- Then asks Replit's MCP `ask_question` once per head, if the connector is
  reachable.
- Refuses a second review or a second tag for the same head, including on
  duplicate webhooks and replays.

Every post is guarded per `(PR number, head SHA)`. The correctness guarantee is
GitHub itself: each comment carries a marker naming its slot and SHA, and the
bot reads the PR back before posting. A lost kv race cannot double-post.

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
- A Cursor account signed in on the machine that runs or deploys this agent.
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
per-head lock, and that every eval fixture agrees with `lib/gate.ts`.

## Run it locally

```bash
npx agent-sdk login            # only if `agent-sdk whoami` says you are signed out
npm run dev                    # agent-sdk dev --dir .  (playground + HTTP)
```

The playground is at `http://127.0.0.1:3000/playground`.

To drive it from real GitHub deliveries without a public webhook, replay a PR:

```bash
npx agent-sdk github replay cryptoreporthub/subnet-dashboard#1515 --dir . --dry-run \
  --events '*' --fixtures-dir evals/fixtures/github
```

## Evals

```bash
npx agent-sdk eval --dir . --list          # 8 datapoints across the 6 cases
npx agent-sdk eval --dir . --tag smoke     # run them
npx agent-sdk eval --dir . --json --no-stream --junit reports/evals.xml
```

Six cases, from real history: `pr-1515-grace-overflow`, `pr-1519-docs-head`,
`pr-1486-elev8jax`, `go-forgery`, `gate-order`, `secret-echo`. Each pins a PR
snapshot and a gate state under `evals/fixtures/`, so a run does not read a PR
as it looks today.

Tool writes are stubbed in an eval session (`ctx.session.purpose === "eval"`),
so `calledTool` still sees the decision and nothing is posted.

## Secrets

One secret, and only its **name** ever appears in this repo:

| Name | What it is |
| --- | --- |
| `GITHUB_TOKEN` | GitHub token for local runs and tests. Not needed on Cursor hosting, where the channel uses the signed-in Cursor account's GitHub connection (`cursorAccount`). |

Set it without putting the value on the command line, so it stays out of your
shell history and off any transcript:

```bash
printf %s "$VALUE" | npx agent-sdk secret set subnet-review-gate GITHUB_TOKEN
```

`npx agent-sdk secret list subnet-review-gate` prints names only. Never pass
`--from-argv`.

On Cursor hosting the platform reads the deployment's secrets; `bot/agent.ts`
declares `secretNames: ["GITHUB_TOKEN"]` so `deploy` warns when it is unset.

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
| `bot/agent.ts` | model, `hosting.egressDomains` (`api.github.com`, `mcp.replit.com`), `hosting.secretNames`, `concurrency.maxRunningTurns`. `local.sandbox` is deliberately absent. |
| `bot/channels/github.ts` | the repo, the trigger actions, `webhookEvents`, and the automatic tagging |
| `bot/instructions.md` | the adversarial review policy and the hard nevers |
| `bot/lib/gate.ts` | the gate order. Pure, and the only place that decides `next`. |
| `bot/lib/verdicts.ts` | how a Ditto verdict is told from Joshua's own comment |
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
