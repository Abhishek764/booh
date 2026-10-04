import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("frontend uses the versioned API health path", async () => {
  const apiModule = await readFile(
    new URL("../src/lib/api.ts", import.meta.url),
    "utf8",
  );

  assert.match(apiModule, /API_V1_PREFIX\s*=\s*["']\/api\/v1["']/);
  assert.match(apiModule, /HEALTH_PATH\s*=\s*`\$\{API_V1_PREFIX\}\/health`/);
});
