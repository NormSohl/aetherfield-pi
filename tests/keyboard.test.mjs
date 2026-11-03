// Run with: node --test tests/keyboard.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { LAYERS } from "../static/keyboard.js";

test("every character a WPA password can hold can be typed", () => {
  const keys = new Set(Object.values(LAYERS).join("") + " ");
  for (let code = 32; code < 127; code += 1) {
    const character = String.fromCharCode(code);
    assert.ok(keys.has(character), `missing ${character}`);
  }
});

test("no row is wider than the screen can hold", () => {
  for (const rows of Object.values(LAYERS)) {
    for (const row of rows) assert.ok(row.length <= 10, row);
  }
});
