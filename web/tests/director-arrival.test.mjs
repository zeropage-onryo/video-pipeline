import test from "node:test";
import assert from "node:assert/strict";
import { openable, pickArrival } from "../src/lib/director-arrival.ts";

const scene = (id, over = {}) => ({ id, is_scene: true, archived: false, prompt: "a written scene", media_url: "", ...over });

test("arrival is the newest scene still waiting on work", () => {
  // the board lists newest first
  const rows = [scene(9, { media_url: "/renders/x.mp4" }), scene(8), scene(7)];
  assert.equal(pickArrival(rows).id, 8);
});

test("a rendered scene is the fallback, so arrival is still a real graph", () => {
  assert.equal(pickArrival([scene(9, { media_url: "/renders/x.mp4" })]).id, 9);
});

test("what the canvas cannot open is never the arrival", () => {
  const rows = [
    scene(9, { archived: true }),
    scene(8, { prompt: "   " }),
    scene(7, { is_scene: false }),
    scene(6, { prompt: null }),
  ];
  assert.equal(pickArrival(rows), null);
  assert.deepEqual(rows.map(openable), [false, false, false, false]);
});

test("an empty board has no arrival -- the caller falls back to the draft", () => {
  assert.equal(pickArrival([]), null);
});
