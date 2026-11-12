// The side-chat smoke suite.
//
// A headless browser drives the real widget end to end.  These are the
// properties the conversation model and the live panel rest on, and
// they only exist once a real Desk, a real login and a real bundle are
// involved — which is why they are not in the unit or domain suites:
//
// *   the panel opens the reader's most recent thread on mount, with
//     the seeded messages on screen;
// *   a message asked from another page carries exactly one "Asked
//     from" chip, naming that page;
// *   the drawer describes threads without pages;
// *   a thread longer than the window offers "Show N earlier messages"
//     with the true count, and the page behind the window carries its
//     turn dividers too;
// *   moving through the Desk leaves the transcript exactly as it was;
// *   a turn that wrote a file offers Undo, and taking it back deletes
//     the file and spends the button;
// *   the pending questions of a thread arrive as one wizard card set —
//     one choice per question when it is single, many when it is not,
//     Submit until every question is answered — and submitting sends
//     the answers as one turn whose activity line ticks;
// *   the page throws no uncaught errors.
//
// It boots its own dev server on a scratch port (FRAPPE_SITE pins the
// site), seeds its own fixture, and tears both down again, so it
// depends on no production ingress and touches no production data.
// The one thing it does beyond the site is talk to the configured
// model, once, at the end: submitting the seeded answers sends a real
// turn, and the ticking clock can only be watched on a turn that runs.
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
// Site and site admin are not needed; the fixture user it logs in as
// is created by `albanna.tests.ui_seed.seed` (password it owns).

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

// How many turns the fixture's long thread holds.  Must match
// LONG_TURNS in albanna/tests/ui_seed.py: the window maths below is
// written against it.
const LONG_TURNS = 29;

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
	const seedOut = execSync(`bench --site ${SITE} execute albanna.tests.ui_seed.seed`, {
		cwd: BENCH_ROOT,
		encoding: "utf8",
	});
	const fixture = JSON.parse(seedOut.trim().split("\n").pop());

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
		await run({ playwrightPath, chrome, base, fixture });
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

async function run({ playwrightPath, chrome, base, fixture }) {
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
	const dividers = () => page.locator(".albanna-chat__message--turn-start").count();
	const drawer = async () => {
		await page.locator(".albanna-chat__icon[aria-label='Conversations']").first().click();
		await page.locator(".albanna-drawer__item").first().waitFor({ timeout: 10000 });
	};
	const probeStatus = () =>
		page.evaluate(
			(url) => fetch(url).then((r) => r.status),
			`${base}/api/resource/File/${fixture.file}`,
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
		// one, with its messages on screen.
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

		log("The day a turn ran on is named above it");
		const days = await page.locator(".albanna-chat__day").allTextContents();
		check(
			"the backdated first turn and today's turn each open a divider",
			days.length === 2,
			JSON.stringify(days),
		);
		check(
			"exactly one divider says Today",
			days.filter((d) => d.trim() === "Today").length === 1,
			JSON.stringify(days),
		);

		log("The drawer describes threads without pages");
		await drawer();
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

		log("The long thread sits behind its window");
		await page
			.locator(".albanna-drawer__item", { hasText: "SMOKE: a long thread" })
			.first()
			.click();
		const earlier = page.locator(".albanna-chat__earlier");
		await earlier.waitFor({ timeout: 15000 });
		const earlierLabel = (await earlier.textContent()).trim().replace(/\s+/g, " ");
		check(
			"the button names the count behind the window",
			earlierLabel === `Show ${LONG_TURNS * 2 - 50} earlier messages`,
			earlierLabel,
		);
		const dividersBefore = await dividers();
		check(
			"turn dividers open each exchange in the window",
			dividersBefore === LONG_TURNS - 5,
			`${dividersBefore} of ${LONG_TURNS - 5}`,
		);
		await earlier.click();
		await earlier.waitFor({ state: "detached", timeout: 20000 });
		const dividersAfter = await dividers();
		check(
			"the earlier page carries its dividers too",
			dividersAfter === LONG_TURNS - 1,
			`${dividersAfter} of ${LONG_TURNS - 1}`,
		);

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

		log("Back to the main thread, where the undo turn waits");
		await drawer();
		await page.locator(".albanna-drawer__item").first().click();
		await page
			.locator(".albanna-chat__bubble", { hasText: "SMOKE: how many open sales orders" })
			.first()
			.waitFor({ timeout: 15000 });
		const undoButton = page
			.locator(".albanna-chat__message", { hasText: "wrote undo-probe" })
			.locator("button[aria-label='Undo this turn']");
		await undoButton.waitFor({ timeout: 10000 });
		check("the undo turn offers Undo", (await undoButton.count()) === 1);
		check("the probe file exists before the undo", (await probeStatus()) === 200);
		await undoButton.click();
		await undoButton.waitFor({ state: "detached", timeout: 20000 });
		check("the Undo button is spent", (await undoButton.count()) === 0);
		await page.waitForTimeout(1000);
		check("the probe file is gone", (await probeStatus()) === 404);

		log("The pending questions arrive as one card set");
		// The wizard shows one question at a time, so there is one card
		// element whose content follows the reader through the set.  It
		// is found by position and held; the check below pins its
		// *starting* content to the fixture's first question, so a
		// regression in the set's order names itself instead of
		// misaligning every later step.
		const card = page.locator(".albanna-chat__question").first();
		await card.waitFor({ timeout: 15000 });
		const submit = card.locator(".albanna-chat__question-submit");
		const progress = (await card.locator(".albanna-chat__question-progress").textContent())
			.trim()
			.replace(/\s+/g, " ");
		check("the wizard starts at the first of two questions", progress === "1 / 2", progress);
		const openingText = (await card.textContent().catch(() => "")).replace(/\s+/g, " ");
		check(
			"the wizard opens on the question that was asked first",
			openingText.includes("SMOKE: pick a priority"),
			openingText.trim().slice(0, 100),
		);
		check("Submit waits until every question is answered", await submit.isDisabled());

		const option = (text) => card.locator(".albanna-chat__question-option", { hasText: text });
		const selected = (text) =>
			option(text).evaluate((el) => el.classList.contains("is-selected"));
		try {
			await option("High").click({ timeout: 15000 });
		} catch (failure) {
			// The card that failed is the card worth reading: dump every
			// card's text and options, so a future flake names itself.
			const cards = await page
				.evaluate(() =>
					Array.from(document.querySelectorAll(".albanna-chat__question")).map((el) => ({
						text: (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 100),
						options: Array.from(el.querySelectorAll(".albanna-chat__question-option")).map(
							(o) => (o.textContent || "").trim(),
						),
					})),
				)
				.catch(() => []);
			check("the wizard's first question is still on screen", false, JSON.stringify(cards));
		}
		check("the single choice takes one option", await selected("High"));
		await option("Low").click();
		check(
			"and replaces it, not adds to it",
			(await selected("Low")) && !(await selected("High")),
		);
		await card.locator(".albanna-chat__question-nav-btn", { hasText: "Next" }).click();
		await option("Red").click();
		await option("Blue").click();
		check(
			"the multiple choice takes several options",
			(await selected("Red")) && (await selected("Blue")),
		);
		await option("Red").click();
		check("and toggles one back off", !(await selected("Red")) && (await selected("Blue")));
		await option("Red").click();
		await card.locator(".albanna-chat__question-nav-btn", { hasText: "Back" }).click();
		check("the walk back keeps the first answer", (await selected("Low")) && !(await selected("High")));
		await card.locator(".albanna-chat__question-nav-btn", { hasText: "Next" }).click();
		check(
			"and the second one",
			(await selected("Red")) && (await selected("Blue")),
		);
		check("Submit is ready once every question is answered", !(await submit.isDisabled()));

		log("The answers go out as one turn, whose clock ticks");
		await submit.click();
		const activity = page.locator(".albanna-chat__activity-text").first();
		await activity.waitFor({ timeout: 30000 }).catch(() => {});
		const turned = await activity.isVisible();
		if (!turned) {
			check("the turn starts", false, "no activity line within 30s");
		} else {
			check("the turn starts", true);
			await page
				.waitForFunction(
					() => {
						const el = document.querySelector(".albanna-chat__activity-text");
						return el && el.textContent.includes("·");
					},
					null,
					{ timeout: 20000 },
				)
				.catch(() => {});
			const t1 = await activity.textContent();
			await page.waitForTimeout(2500);
			const t2 = (await activity.isVisible()) ? await activity.textContent() : "";
			check(
				"the activity clock ticks",
				t1 !== t2 && t2.length > 0,
				`${t1.trim()} -> ${t2.trim()}`,
			);
			const ended = await page
				.waitForSelector(".albanna-chat__activity", { state: "detached", timeout: 180000 })
				.then(() => true)
				.catch(() => false);
			check("the turn ends", ended, "the activity line stayed up for 180s");
			// The edit below needs the turn to have *succeeded*: a turn
			// the provider refused wrote no rows, so its question has
			// nothing to edit.  Say so here rather than let the Edit
			// button's wait time out with nothing to read.
			const turnError = await page
				.locator(".albanna-chat__error")
				.textContent()
				.catch(() => null);
			check("the turn did not end in an error", !turnError, (turnError || "").trim());
		}

		log("The last question can be edited, and its answer made again");
		const lastUser = () => page.locator(".albanna-chat__message--user").last();
		const lastWords = (await lastUser().locator(".albanna-chat__bubble--plain").textContent())
			.trim()
			.replace(/\s+/g, " ");
		const editButton = lastUser().locator("button[aria-label='Edit this question']");
		await editButton.waitFor({ timeout: 10000 });
		check("the last question offers Edit", (await editButton.count()) === 1);
		await editButton.click();
		const editor = lastUser().locator(".albanna-chat__edit-input");
		await editor.waitFor({ timeout: 5000 });
		const opened = (await editor.inputValue()).replace(/\s+/g, " ");
		check("the editor opens with the words in it", opened === lastWords, opened);
		await editor.fill("SMOKE: the question was edited.");
		await lastUser().locator(".albanna-chat__edit-save").click();
		await page
			.locator(".albanna-chat__bubble--plain", { hasText: "SMOKE: the question was edited." })
			.first()
			.waitFor({ timeout: 10000 });
		check(
			"the edited question takes the old one's place",
			(await page.locator(".albanna-chat__bubble--plain", { hasText: lastWords }).count()) === 0,
			lastWords,
		);
		// The turn the edit queued runs like any other: the activity line
		// comes up for it and goes when it is done.
		const reEdit = await page
			.waitForSelector(".albanna-chat__activity", { state: "attached", timeout: 20000 })
			.then(() => true)
			.catch(() => false);
		const reEnded = await page
			.waitForSelector(".albanna-chat__activity", { state: "detached", timeout: 180000 })
			.then(() => true)
			.catch(() => false);
		check("the edited turn runs and ends", reEdit && reEnded, `ran=${reEdit} ended=${reEnded}`);
	} finally {
		await page.close().catch(() => {});
		await browser.close().catch(() => {});
	}
}

main().catch((error) => {
	console.error(`SMOKE: aborted — ${error.message}`);
	process.exit(1);
});
