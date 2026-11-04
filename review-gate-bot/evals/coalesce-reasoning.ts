/**
 * Keeps one review's event log from growing with the square of its reasoning.
 *
 * Root cause (hex-words / failed-read hang, #1522 r2): the SDK's `TurnEventMapper` emits one
 * `reasoning.appended` event per streamed token chunk (about 20 characters), and every event carries
 * both the `delta` and the whole reasoning text so far (`data.text`). A reasoning block of N
 * characters therefore writes about N * N / 40 bytes. At `reasoning_effort: max` the bot writes blocks
 * of 20-56 KB, 11 of them in one 6-minute run: 35,237 events, 758 MB of `events.ndjson`, held again in
 * memory and serialised whole by the `GET /sessions/:id/events?format=json` read the eval driver
 * makes at the end of a turn. That string passes V8's ~512 MB limit (`RangeError: Invalid string
 * length`) or the heap (`FATAL ERROR: ... JavaScript heap out of memory`), and the run is lost.
 *
 * Fix: merge token chunks into one `thinking-delta` of at least `FLUSH_CHARS` before the mapper sees
 * it. The reasoning text, its order against tool calls and `reasoning.completed` are unchanged; only
 * the number of events drops, by about 200x (the stream interleaves a `token-delta` usage update with almost every chunk; those emit nothing, so they do not flush), and the log by the same factor. Nothing is deleted and
 * the reasoning effort is not touched. The patch is loaded by `evals.config.ts`, so it applies to the
 * eval server only, never to the deployed bot.
 */
export const FLUSH_CHARS = 4096;

/**
 * Updates the mapper accepts and drops without emitting an event (see its `handleUpdate`). The model stream
 * interleaves one `token-delta` (usage) with almost every reasoning chunk, so flushing on them would undo the merge.
 */
const NO_EVENT_UPDATES = new Set(["token-delta", "partial-tool-call", "summary-started", "summary-completed", "shell-output-delta"]);

type Update = { type: string; text?: string; [key: string]: unknown };
type Mapper = { handleUpdate(update: Update): void };

const PATCHED = Symbol.for("review-gate-bot.coalesce-reasoning");

/** Wrap `handleUpdate` of any mapper-shaped prototype. Exported so the unit test can use a stand-in. */
export function coalesceReasoning(proto: Mapper, flushChars: number = FLUSH_CHARS): boolean {
  const target = proto as unknown as Record<symbol, boolean>;
  if (target[PATCHED] === true) return false;
  target[PATCHED] = true;
  const original = proto.handleUpdate;
  const pending = new WeakMap<object, { update: Update; text: string }>();
  proto.handleUpdate = function (this: object, update: Update): void {
    const held = pending.get(this);
    if (update.type === "thinking-delta" && typeof update.text === "string") {
      const text = (held?.text ?? "") + update.text;
      if (text.length < flushChars) {
        pending.set(this, { update, text });
        return;
      }
      pending.delete(this);
      original.call(this, { ...update, text });
      return;
    }
    if (held !== undefined && !NO_EVENT_UPDATES.has(update.type)) {
      pending.delete(this);
      original.call(this, { ...held.update, text: held.text });
    }
    original.call(this, update);
  };
  return true;
}

/** Patch the SDK mapper the eval server uses. Resolves the same module file the SDK imports. */
export async function installReasoningCoalescing(): Promise<boolean> {
  const url = new URL("../node_modules/@grok/agent-sdk/dist/internal/event-mapper.js", import.meta.url).href;
  const mod = (await import(/* @vite-ignore */ url)) as { TurnEventMapper: { prototype: Mapper } };
  return coalesceReasoning(mod.TurnEventMapper.prototype);
}
