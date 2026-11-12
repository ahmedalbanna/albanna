// The side-chat smoke suite.
//
// A headless browser drives the real widget end to end: the panel opens
// the reader's most recent thread, a message asked from another page
// carries its chip, the drawer describes threads without pages, and
// moving through the Desk leaves the thread open.  These are the
// properties the conversation model now rests on, and they only exist
// once a real Desk, a real login and a real bundle are involved — which
// is why they are not in the unit or domain suites.
//
// It boots its own dev server on a scratch port (FRAPPE_SITE pins the
// site), seeds its own fixture, and tears both down again, so it
// depends on no production ingress and touches no production data.
//
// Run from anywhere:
//
//     node scripts/ui_smoke.mjs
//
// Needs `playwright-core` resolvable (app node_modules, or
// ALBANNA_SMOKE_NODE_MODULES pointing at a node_modules that has it)
// and a Chrome binary (ALBANNA_SMOKE_CHROME, or the newest
// ~/.cache/ms-playwright/chromium-*).  With neither, the suite *skips*
// — exit 0, loudly — because a missing browser is a missing capability,
// not a failing property.
//
// Site and site admin are not needed; the fixture user it logs in as is
// created by `albanna.tests.ui_seed.seed` (password it owns).

import { spawn, execSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BENCH_ROOT = path.resolve(APP_ROOT, "..", "..");
const SITE = process.env.ALBANNA_SMOKE_SITE || "test.localhost";

const failures = [];
const pageErrors = [];
const log = (m) => console.log(m);
const check = (name, ok, detail = "") => {
	log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
	if (!ok) failures.push(name);
};

function skip(reason) {
	log(`SKIP: ${reason}`);
	process.exit(0);
}

function resolvePlaywright() {
	const require = createRequire(import.meta.url);
	const paths = [process.env.ALBANNA_SMOKE_NODE_MODULES, path.join(APP_ROOT, "node_modules")].filter(
		Boolean,
	);
	try {
		return require.resolve("playwright-core", { paths });
	} catch {
		return null;
	}
}

function resolveChrome() {
	if (process.env.ALBANNA_SMOKE_CHROME) return process.env.ALBANNA_SMOKE_CHROME;
	const cache = path.join(os.homedir(), ".cache", "ms-playwright");
	let best = null;
	try {
		for (const dir of fs.readdirSync(cache)) {
			const match = dir.match(/^chromium-(\d+)$/);
			if (!match) continue;
			for (const inner of ["chrome-linux64", "chrome-linux"]) {
				const candidate = path.join(cache, dir, inner, "chrome");
				if (fs.existsSync(candidate)) {
					const version = Number(match[1]);
					if (!best || version > best.version) best = { version, path: candidate };
				}
			}
		}
	} catch {
		return null;
	}
	return best ? best.path : null;
}

function freePort() {
	return new Promise((resolve, reject) => {
		const server = net.createServer();
		server.listen(0, "127.0.0.1", () => {
			const { port } = server.address();
			server.close(() => resolve(port));
		});
		server.on("error", reject);
	});
}

async function waitForServer(base, tries = 40) {
	for (let i = 0; i < tries; i += 1) {
		try {
			const response = await fetch(`${base}/login`);
			if (response.ok) return true;
		} catch {
			// not up yet
		}
		await new Promise((r) => setTimeout(r, 500));
	}
	return false;
}

async function main() {
	const playwrightPath = resolvePlaywright();
	if (!playwrightPath) skip("playwright-core not found (set ALBANNA_SMOKE_NODE_MODULES)");
	const chrome = resolveChrome();
	if (!chrome) skip("no Chrome binary (set ALBANNA_SMOKE_CHROME)");

	log(`Seeding the fixture on ${SITE}…`);
	execSync(`bench --site ${SITE} execute albanna.tests.ui_seed.seed`, {
		cwd: BENCH_ROOT,
		stdio: "inherit",
	});

	const port = await freePort();
	const base = `http://127.0.0.1:${port}`;
	log(`Booting the dev server on ${base} (${SITE})…`);
	const server = spawn("bench", ["serve", "--port", String(port), "--noreload"], {
		cwd: BENCH_ROOT,
		env: { ...process.env, FRAPPE_SITE: SITE },
		stdio: ["ignore", "ignore", "ignore"],
	});
	if (!(await waitForServer(base))) {
		server.kill();
		throw new Error(`the dev server on ${base} never came up`);
	}

	try {
		await run({ playwrightPath, chrome, base });
	} finally {
		server.kill("SIGTERM");
	}

	if (pageErrors.length) {
		log("  FAIL  no page errors");
		for (const error of pageErrors) log(`        ${error.slice(0, 300)}`);
		failures.push("no page errors");
	}

	log("");
	if (failures.length) {
		log(`SMOKE: ${failures.length} failed — ${failures.join("; ")}`);
		process.exit(1);
	}
	log("SMOKE: all checks passed");
}

async function run({ playwrightPath, chrome, base }) {
	const mod = await import(playwrightPath);
	const chromium = mod.chromium || mod.default?.chromium;
	const browser = await chromium.launch({
		executablePath: chrome,
		headless: true,
		args: ["--no-sandbox"],
	});
	const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
	page.on("pageerror", (err) => pageErrors.push(String(err)));
	const bubbles = () =>
		page.evaluate(() =>
			document.querySelectorAll(".albanna-chat__bubble, .albanna-chat__bubble--plain").length,
		);

	try {
		await page.goto(`${base}/login`, { waitUntil: "domcontentloaded" });
		await page.fill("#login_email", "albanna.smoke@albanna.dev");
		await page.fill("#login_password", "albanna-smoke-pass");
		await Promise.all([
			page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {}),
			page.click(".btn-login"),
		]);
		await page.waitForTimeout(3000);

		// The panel opens the reader's most recent thread — the seeded
		// one, with its three messages on screen.
		log("The panel opens on the reader's most recent thread");
		await page.locator(".albanna-side-chat-launcher").first().click();
		await page
			.locator(".albanna-chat__bubble--plain", { hasText: "SMOKE: how many open sales orders" })
			.first()
			.waitFor({ timeout: 20000 });
		const count = await bubbles();
		check("the seeded thread is open on mount", count >= 3, `${count} bubbles`);
		check(
			"the cross-page answer is on screen",
			(await page
				.locator(".albanna-chat__bubble", { hasText: "SMOKE: this one was asked from an Item." })
				.count()) >= 1,
		);

		log("A message asked from another page carries its chip");
		const chips = await page.locator(".albanna-chat__from-page").allTextContents();
		check(
			"exactly one chip, naming the page",
			chips.length === 1 && chips[0].includes("Item"),
			JSON.stringify(chips),
		);

		log("The drawer describes threads without pages");
		await page.locator(".albanna-chat__icon[aria-label='Conversations']").first().click();
		await page.locator(".albanna-drawer__item").first().waitFor({ timeout: 10000 });
		const metas = await page.evaluate(() =>
			Array.from(document.querySelectorAll(".albanna-drawer__meta")).map((el) =>
				el.textContent.trim().replace(/\s+/g, " "),
			),
		);
		check(
			"no meta line shows a page identity",
			metas.length > 0 && metas.every((m) => !m.includes("SMOKE-PROBE") && !m.includes("form|")),
			JSON.stringify(metas.slice(0, 3)),
		);

		log("Opening a thread from the drawer");
		await page.locator(".albanna-drawer__item").first().click();
		await page.waitForTimeout(2000);
		const reopened = await bubbles();
		check("the thread is open again", reopened >= 3, `${reopened} bubbles`);

		log("Moving through the Desk keeps the thread open");
		const beforeNav = await bubbles();
		await page.evaluate(() => {
			const link = Array.from(document.querySelectorAll("a[href]")).find(
				(a) => a.getAttribute("href").startsWith("/app/") && a.getAttribute("href") !== "/app",
			);
			if (link) link.click();
		});
		await page.waitForTimeout(3000);
		const afterNav = await bubbles();
		check(
			"the transcript survives the route change",
			afterNav === beforeNav && afterNav >= 3,
			`${beforeNav} -> ${afterNav}`,
		);
	} finally {
		await page.close().catch(() => {});
		await browser.close().catch(() => {});
	}
}

main().catch((error) => {
	console.error(`SMOKE: aborted — ${error.message}`);
	process.exit(1);
});
