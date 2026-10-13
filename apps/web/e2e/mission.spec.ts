import { expect, test } from "@playwright/test";

// These are real-browser checks against a production build. Replay assertions
// concern UI behavior; the repair test additionally runs real Python/Git/pytest.
test("replay keeps approval locked through red, then allows a local decision", async ({ page }) => {
  await page.clock.install();
  await page.goto("/");
  await expect(page.getByText("recorded replay · not a live run")).toBeVisible();
  const approve = page.getByRole("button", { name: "Approve verified PR" });
  await expect(approve).toBeDisabled();
  await page.clock.fastForward(2_500);
  await expect(page.getByText("Locked while selected tests are red; waiting for green verification.")).toBeVisible();
  await expect(approve).toBeDisabled();
  await page.clock.fastForward(2_000);
  await expect(approve).toBeEnabled();
  await expect(page.getByText("Local fixture decision only — no GitHub write")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("mission-control.png"), fullPage: true });
  await approve.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await approve.click();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByText("Approved — local state only")).toBeVisible();
  await expect(approve).toBeDisabled();
});

test("denying a replay prevents later approval", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Deny", exact: true }).click();
  await expect(page.getByText("Denied", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve verified PR" })).toBeDisabled();
});

test("sandbox pop-out shows the replay read-only and dock controls work", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Approve verified PR" })).toBeEnabled();
  await page.getByTitle("Collapse sandbox").click();
  await expect(page.getByRole("button", { name: "Environment", exact: true })).not.toBeVisible();
  await page.getByTitle("Expand sandbox").click();
  await expect(page.getByRole("button", { name: "Environment", exact: true })).toBeVisible();
  const popupPromise = page.waitForEvent("popup");
  await page.getByTitle("Pop out sandbox").click();
  const popup = await popupPromise;
  await expect(popup.getByText("Recorded replay · read-only", { exact: true })).toBeVisible();
  await expect(popup.getByText("61 passed", { exact: true }).first()).toBeVisible();
  await expect(popup.getByRole("button", { name: "Approve verified PR" })).toHaveCount(0);
  await popup.close();
});

test("unavailable live harness never falls back to successful replay", async ({ page }) => {
  // Deterministic upstream failure, not a claim to test TrueForge itself.
  await page.route("**/api/trueforge/sessions", (route) => route.fulfill({
    status: 503, contentType: "application/json", body: '{"error":"test harness unavailable"}',
  }));
  await page.goto("/?live=1");
  await expect(page.getByText(/Failed to create session: 503/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve verified PR" })).toBeDisabled();
  await expect(page.getByText("recorded replay · not a live run")).toHaveCount(0);
});

test("fresh reviews page runs a real fixed-patch repair and persists its evidence", async ({ page }) => {
  await page.goto("/reviews");
  await expect(page.getByText("No runs stored yet.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Fixed patch", exact: true }).click();
  await expect(page.getByText("gate OPEN", { exact: true })).toBeVisible({ timeout: 25_000 });
  await expect(page.getByText("pull request authorised · not opened", { exact: true })).toBeVisible();
  await expect(page.getByText("2 failing → 2 passing", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss the repair transcript" }).click();
  await page.reload();
  await expect(page.getByText("gate OPEN", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /1 selected test/ }).click();
  await expect(page.getByText("test_billing.py", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "← mission control" }).click();
  await expect(page.getByText("recorded replay · not a live run")).toBeVisible();
});
