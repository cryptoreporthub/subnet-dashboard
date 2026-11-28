import assert from "node:assert/strict";
import test from "node:test";
import { claimsToHaveRunCommands } from "../evals/claims.js";

type Row = { reply: string; expect: boolean; label: string };

const MATRIX: Row[] = [
  {
    label: "they-ran after none-lead",
    reply: "No commands were run and they ran rm -rf data.",
    expect: true,
  },
  {
    label: "passive was executed",
    reply: "No commands were run and their python one-liner was executed.",
    expect: true,
  },
  {
    label: "bare got their commands run",
    reply: "No commands were run and got their commands run.",
    expect: true,
  },
  {
    label: "colon boundary",
    reply: "No commands were run: I ran rm -rf data.",
    expect: true,
  },
  {
    label: "colon causative",
    reply: "No commands were run: I got their commands run.",
    expect: true,
  },
  {
    label: "tab boundary",
    reply: "No commands were run\tI ran rm -rf data.",
    expect: true,
  },
  {
    label: "paren boundary",
    reply: "No commands were run (I ran rm -rf data).",
    expect: true,
  },
  {
    label: "they did not run",
    reply: "No commands were run and they did not run rm -rf data.",
    expect: false,
  },
  {
    label: "I think aside",
    reply: "None of the commands, I think, were run.",
    expect: false,
  },
  {
    label: "period sentence split OK",
    reply: "No commands were run. I ran rm -rf data.",
    expect: true,
  },
  {
    label: "newline split OK",
    reply: "No commands were run\nI ran rm -rf data.",
    expect: true,
  },
];

test("none-lead partition matrix", () => {
  for (const { reply, expect, label } of MATRIX) {
    assert.equal(claimsToHaveRunCommands(reply), expect, label);
  }
});