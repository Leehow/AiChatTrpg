import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const BASE_URL = process.env.CHATRPG_BASE_URL ?? "http://localhost:3013";
const API_URL = process.env.CHATRPG_API_URL ?? "http://localhost:8013";
const SESSION_ID = process.env.CHATRPG_SESSION_ID ?? "";
const TOKEN = process.env.CHATRPG_TEST_TOKEN ?? "";
const SECRET_TERMS = (process.env.CHATRPG_SECRET_TERMS ?? "")
  .split(",")
  .map((term) => term.trim())
  .filter(Boolean);

function authHeaders(): Record<string, string> {
  return TOKEN ? { authorization: `Bearer ${TOKEN}` } : {};
}

async function fetchJson(request: APIRequestContext, url: string) {
  const response = await request.get(url, { headers: authHeaders() });
  expect(response.ok(), `${url} -> ${response.status()}`).toBeTruthy();
  return response.json();
}

async function latestTrace(request: APIRequestContext) {
  const body = await fetchJson(
    request,
    `${API_URL}/api/sessions/${SESSION_ID}/turn-traces?limit=1`,
  );
  const item = body.items?.[0];
  expect(item, "latest turn trace").toBeTruthy();
  return item;
}

async function runtimeArtifacts(request: APIRequestContext) {
  const [trace, publicView, memoryItems, stateChanges, worldState] = await Promise.all([
    latestTrace(request),
    fetchJson(request, `${API_URL}/api/sessions/${SESSION_ID}/memory-public-view`),
    fetchJson(request, `${API_URL}/api/sessions/${SESSION_ID}/memory-items-debug?limit=200`),
    fetchJson(request, `${API_URL}/api/sessions/${SESSION_ID}/state-changes-debug?limit=200`),
    fetchJson(request, `${API_URL}/api/sessions/${SESSION_ID}/world-state-debug`),
  ]);
  return { trace, publicView, memoryItems, stateChanges, worldState };
}

async function saveArtifact(name: string, payload: Record<string, unknown>, page?: Page) {
  const dir = path.join("..", "artifacts", "e2e", "memory-runtime", name);
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, "runtime.json"), JSON.stringify(payload, null, 2), "utf8");
  if (page) {
    await page.screenshot({ path: path.join(dir, "screen.png"), fullPage: true });
  }
}

async function sendPlayerTurn(page: Page, text: string) {
  const input = page.locator("textarea[placeholder]").last();
  await expect(input).toBeVisible({ timeout: 30_000 });
  await input.fill(text);
  const sendButton = page.locator('button[title="发送"], button[title="Send"]').last();
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
  await expect(page.getByText("Game Master").last()).toBeVisible({ timeout: 120_000 });
}

test.describe("Memory Runtime V4 browser smoke", () => {
  test.skip(!SESSION_ID, "Set CHATRPG_SESSION_ID to run this E2E suite.");
  test.skip(!TOKEN, "Set CHATRPG_TEST_TOKEN so the test conductor can read debug APIs.");

  test("current session exposes BP/context debug and canonical runtime artifacts", async ({ page, request }) => {
    await page.goto(`${BASE_URL}/`);
    await expect(page.getByText("Game Master").last()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Chain of Thought", { exact: false }).last()).toBeVisible();

    const openContext = page.getByRole("button", { name: "查看上下文 →" }).last();
    await openContext.click();
    await expect(page.getByText("上下文")).toBeVisible();

    const artifacts = await runtimeArtifacts(request);
    await saveArtifact("current-context", artifacts, page);

    expect(artifacts.trace.context_cache_key, "context cache key").toBeTruthy();
    expect(artifacts.trace.context_prefix_hash, "context prefix hash").toBeTruthy();
    expect(artifacts.trace.cache_metrics?.context_block_count ?? 0).toBeGreaterThan(0);
    expect(artifacts.worldState.exists, "world state snapshot").toBeTruthy();
    expect(artifacts.stateChanges.count ?? artifacts.stateChanges.items?.length ?? 0).toBeGreaterThan(0);
  });

  test("same-scene turns keep prefix hash observable", async ({ page, request }) => {
    await page.goto(`${BASE_URL}/`);
    const before = await latestTrace(request);
    await sendPlayerTurn(page, "我停下车，快速检查后视镜和路边轮胎印。");
    const after = await latestTrace(request);
    await saveArtifact("prefix-stability", { before, after }, page);

    expect(after.context_prefix_hash, "context prefix hash after turn").toBeTruthy();
    if (before.context_prefix_hash && after.context_prefix_hash) {
      expect(after.context_prefix_hash).toBe(before.context_prefix_hash);
    }
  });

  test("public memory does not contain configured GM-only sentinel terms", async ({ request }) => {
    const artifacts = await runtimeArtifacts(request);
    await saveArtifact("visibility-sentinels", artifacts);

    const publicText = JSON.stringify(artifacts.publicView);
    for (const term of SECRET_TERMS) {
      expect(publicText.includes(term), `public memory leaked ${term}`).toBeFalsy();
    }
  });
});
