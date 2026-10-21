// A small markdown renderer for the chat transcript.
//
// The order is the whole point: the text is **escaped first**, and only
// then are this module's own tags inserted.  Nothing the model or the site
// says can therefore introduce markup — there is nothing left in the
// string that could be markup.
//
// The subset is what an assistant actually produces: headings, bold,
// italic, inline code, fenced code, bullet and numbered lists, pipe
// tables, and line breaks.  It is deliberately not a markdown
// implementation; anything it does not know is left as text, which is the
// correct rendering of a paragraph.
//
// The result is used with `v-html`, which is safe *because* of the escaping
// above, and unsafe for any other reason.  If this module ever changes to
// build HTML from the text without escaping it first, it becomes an
// injection point.

/**
 * Escape the five characters that matter in HTML.
 *
 * @param {string} text
 * @returns {string} the escaped text
 */
export function escapeHtml(text) {
	return String(text ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

/** A table row: a line that starts and ends with a pipe. */
const TABLE_ROW = /^[ \t]*\|.*\|[ \t]*$/;

/** A separator cell: two or more dashes, optionally aligned with colons. */
const SEPARATOR_CELL = /^:?-{2,}:?$/;

/** A heading: one to six hashes and some text. */
const HEADING = /^(#{1,6})\s+(.*)$/;

/**
 * Split a table's row into its cells.
 *
 * Repeated pipes are collapsed first.  Models sometimes write the
 * separator row as `||---|---|---||` rather than `|---|---|---|`, and a
 * table whose separator does not parse is a table that renders as a wall of
 * pipes.
 *
 * @param {string} line
 * @returns {string[]} the cells
 */
function tableCells(line) {
	return line
		.trim()
		.replace(/\|\|+/g, "|")
		.replace(/^\|/, "")
		.replace(/\|$/, "")
		.split("|")
		.map((cell) => cell.trim());
}

/**
 * Is this line a table's separator row?
 *
 * @param {string} line
 * @returns {boolean} true when every cell is a dash
 */
function isSeparatorRow(line) {
	const cells = tableCells(line);
	return cells.length > 0 && cells.every((cell) => SEPARATOR_CELL.test(cell));
}

/**
 * Render a pipe table.
 *
 * The table is wrapped in a scroll container.  A table is the one thing
 * this renderer produces that can be wider than the panel it is shown in,
 * and the panel is 400px: without the wrapper the table is squeezed to
 * fit, and a cell like `Open` breaks across two lines as `Op` / `en` and
 * a date breaks as `2026-` / `06-15`.  A table that cannot be read is
 * worse than one that scrolls.
 *
 * @param {string[]} lines the table's lines, the first two being the header
 *   and the separator
 * @returns {string} the table's HTML
 */
function renderTable(lines) {
	const header = tableCells(lines[0]);
	const rows = lines.slice(2).map(tableCells);

	const head = `<thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>`;
	const body = `<tbody>${rows
		.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
		.join("")}</tbody>`;

	return `<div class="albanna-chat__table-wrap"><table>${head}${body}</table></div>`;
}

/**
 * A markdown link: `[text](url)`.
 *
 * The url may hold one level of parentheses, because a Wikipedia link
 * holds one: `.../Foo_(bar)`.  Two levels is more than any link in an
 * answer needs.
 */
const LINK = /\[([^\]\n]*)\]\(([^()\s]*(?:\([^()\s]*\)[^()\s]*)*)\)/g;

/**
 * Is this a URL the panel may link to?
 *
 * Only http, https and mailto.  Everything else — `javascript:`, `data:`,
 * a bare path — is left as the text it was written as, because a link the
 * reader clicks is the one place the model's output becomes an action
 * rather than a sentence.
 *
 * The text checked is the *escaped* text, which is what the href is built
 * from.  Escaping turns `&` into `&amp;` and `"` into `&quot;`, so a url
 * cannot break out of the attribute; and it leaves the scheme alone, so
 * checking the prefix here checks the scheme the browser will see.  A
 * scheme spelled with an entity — `&#106;avascript:` — arrives escaped
 * and is rejected with everything else.
 *
 * @param {string} url the url as it appears in the escaped text
 * @returns {string|null} the url, or null when it may not be linked
 */
function safeUrl(url) {
	const text = String(url || "")
		.trim()
		.toLowerCase();
	const allowed =
		text.startsWith("http://") || text.startsWith("https://") || text.startsWith("mailto:");
	return allowed ? url : null;
}

/**
 * The placeholders that carry a piece of markup through the renderer.
 *
 * They carry no spaces, because a table cell is trimmed and the spaces
 * around a placeholder would go with it: the code in a table cell came
 * out as the literal text "CODE0".
 *
 * They are wrapped in tildes, which no rule in this renderer treats as
 * anything: a tilde is not a bracket, so it does not break a link's
 * text, and it is not a star or a pipe or a hash, so it does not turn
 * into emphasis, a table or a heading.
 */

/**
 * Put the inline code back into a string that was captured before the
 * code was restored.
 *
 * A link's text is captured while the link is recognised, which is before
 * the code is put back — so a link whose text carries code would show the
 * placeholder.
 *
 * @param {string} text the captured text
 * @param {string[]} codes the inline code, to be restored
 * @returns {string} the text, with its code back
 */
function restoreCode(text, codes) {
	return String(text ?? "").replace(
		/~CODE(\d+)~/g,
		(_match, index) => `<code>${codes[Number(index)]}</code>`,
	);
}

/**
 * Render the inline markdown of one block of text.
 *
 * The block's contents are already escaped.  Code is pulled out first, so
 * that neither the emphasis rules nor the list rules can touch it: a `**`
 * inside a code block is a `**`, and a line starting with `-` inside one is
 * not a bullet.
 *
 * @param {string} block
 * @param {string[]} codes collects the inline code, to be restored
 * @param {object[]} links collects the links, to be restored
 * @returns {string} the block's HTML
 */
function renderInline(block, codes, links) {
	let html = block.replace(/`([^`\n]+)`/g, (_match, code) => {
		codes.push(code);
		return `~CODE${codes.length - 1}~`;
	});

	// Links next, so that a url is never touched by the emphasis rules and
	// an emphasis marker is never read as part of a url.  A link that may
	// not be linked is left exactly as it was written.
	html = html.replace(LINK, (match, text, url) => {
		const safe = safeUrl(url);
		if (!safe) return match;
		links.push({ text, url: safe });
		return `~LINK${links.length - 1}~`;
	});

	// Bold, then italic.  Italic is a single `*` on each side and must not
	// match the `**` that bold has already replaced.
	html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
	html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");

	return html;
}

/** A list item: its indent, its marker, and its text. */
const ITEM = /^([ \t]*)([-*]|\d+[.)])[ \t]+(.*)$/;

/**
 * A blockquote line: `> the quoted text`.
 *
 * The marker is matched in its *escaped* form, because the text is
 * escaped before the block rules run and `>` becomes `&gt;`.  Nothing
 * else can produce `&gt;` in the escaped text — a literal `&gt;` in the
 * model's output arrives as `&amp;gt;` — so the marker is still
 * unambiguous.
 */
const QUOTE = /^[ \t]*&gt;[ \t]?(.*)$/;

/**
 * Render a list, with one level of nesting.
 *
 * An assistant's answer has nested lists, and flattening them loses the
 * structure that made them worth writing.  A line that is not an item is
 * a *continuation* of the item above it — the way a sentence wraps — and
 * it belongs inside that item; the version before this dropped it
 * outside the list altogether, where it read as a stray paragraph.
 *
 * @param {string[]} lines the block's lines
 * @param {string[]} texts the same lines, with the inline markup applied
 * @returns {string} the list's HTML
 */
function renderList(lines, texts) {
	const items = [];
	let current = null;

	for (let index = 0; index < lines.length; index++) {
		const match = lines[index].match(ITEM);
		if (match) {
			// The indent decides the level.  Two spaces is a level, and
			// anything deeper is the same level: a list three deep is more
			// than an answer needs.
			const indent = match[1].replace(/\t/g, "  ").length;
			const level = indent >= 2 ? 1 : 0;
			const text = (texts[index] || "").replace(ITEM, "$3");

			const item = { text, ordered: /^\d/.test(match[2]), children: [] };
			if (level === 0 || !current) {
				items.push(item);
				current = item;
			} else {
				current.children.push(item);
			}
			continue;
		}

		// A continuation of the item above.
		if (current) {
			current.text += "\n" + (texts[index] || "").trim();
		}
	}

	return renderListItems(items);
}

/**
 * Render a list's items, and the lists under them.
 *
 * @param {object[]} items the items
 * @returns {string} the list's HTML
 */
function renderListItems(items) {
	if (!items.length) return "";
	const tag = items[0].ordered ? "ol" : "ul";
	const html = items
		.map((item) => {
			const children = item.children.length ? renderListItems(item.children) : "";
			return `<li>${item.text.replace(/\n/g, "<br>")}${children}</li>`;
		})
		.join("");
	return `<${tag}>${html}</${tag}>`;
}

/**
 * Render one block: a heading, a table, a list, a quote, or a paragraph.
 *
 * @param {string} block
 * @param {string[]} codes collects the inline code
 * @param {object[]} links collects the links
 * @returns {string} the block's HTML
 */
function renderBlock(block, codes, links) {
	const lines = block.split("\n");

	// A heading is the first line of a block, and the rest of the block is
	// whatever follows it — a model does not leave a blank line between a
	// heading and its text.
	const heading = lines[0].match(HEADING);
	if (heading) {
		// `#` is the page's title, so the panel's headings start at `h2`.
		const level = Math.min(heading[1].length + 1, 5);
		const rest = lines.slice(1).join("\n");
		const head = `<h${level}>${renderInline(heading[2], codes, links)}</h${level}>`;
		return rest.trim() ? head + renderBlock(rest, codes, links) : head;
	}

	// The inline rules run before the table is recognised, so that a cell's
	// `**bold**` is already marked up by the time the row is split.
	const body = renderInline(block, codes, links);

	// A quote.  An assistant uses it for the aside — the note, the
	// caveat, the "this is only true as of today" — and a block of
	// quoted lines is a block of quoted lines.
	if (lines.every((line) => QUOTE.test(line))) {
		const quoted = lines.map((line) => line.replace(QUOTE, "$1")).join("\n");
		return `<blockquote>${renderInline(
			quoted.replace(/\n/g, "<br>"),
			codes,
			links,
		)}</blockquote>`;
	}

	if (lines.length >= 2 && TABLE_ROW.test(lines[0]) && isSeparatorRow(lines[1])) {
		return renderTable(body.split("\n"));
	}

	if (/^[ \t]*([-*]|\d+[.)])[ \t]+/.test(lines[0])) {
		return renderList(lines, body.split("\n"));
	}

	return `<p>${body.replace(/\n/g, "<br>")}</p>`;
}

/**
 * Escape a string for use in a regular expression.
 *
 * @param {string} text the string
 * @returns {string} the escaped string
 */
function escapeRegExp(text) {
	return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Turn the document names in *text* into links.
 *
 * The names are matched whole and in full.  "SAL-ORD-2026-0001" inside
 * "SAL-ORD-2026-00012" is not the same document, and a link that opens
 * the wrong one is worse than no link at all.
 *
 * The names come from the tools the assistant called, so a word in the
 * answer is only ever a link when it *is* a document name.  Nothing is
 * guessed from the shape of the text.
 *
 * @param {string} text the escaped text
 * @param {object[]} documents the documents, each a `{name, url}` pair
 * @param {object[]} links collects the links, to be restored
 * @returns {string} the text, with the names behind placeholders
 */
function linkDocuments(text, documents, links) {
	const named = documents
		.filter((document) => document && document.name && document.url)
		// Longest first, so that a name that is the beginning of another
		// one is matched whole.
		.sort((a, b) => String(b.name).length - String(a.name).length);

	if (!named.length) return text;

	const pattern = new RegExp(
		`(?:${named.map((document) => escapeRegExp(document.name)).join("|")})`,
		"g",
	);

	return text.replace(pattern, (match, offset, whole) => {
		// The name has to stand on its own: a name with a word character
		// against it is a part of a longer word, not a document name.
		const before = offset > 0 ? whole[offset - 1] : "";
		const after = whole[offset + match.length] || "";
		if ((before && /[\w-]/.test(before)) || (after && /[\w-]/.test(after))) {
			return match;
		}

		const document = named.find((entry) => entry.name === match);
		if (!document) return match;

		links.push({ text: match, url: document.url });
		return `~LINK${links.length - 1}~`;
	});
}

/**
 * The rows of the first table in *text*, as tab-separated values.
 *
 * A table in an answer is data, and data goes into a spreadsheet.  The
 * tabs are what a spreadsheet expects, and the first row is the header,
 * so the paste lands as a table rather than as a column of text.
 *
 * @param {string} text the answer
 * @returns {string} the table, as tab-separated values
 */
export function tableAsTsv(text) {
	const rows = [];
	let inside = false;

	for (const line of String(text || "").split("\n")) {
		if (!TABLE_ROW.test(line)) {
			if (inside) break;
			continue;
		}
		inside = true;

		const cells = line
			.trim()
			.replace(/^\|/, "")
			.replace(/\|$/, "")
			.split("|")
			// The markdown is not data.  A spreadsheet reading "**24**" is
			// reading the emphasis, not the number.
			.map((cell) =>
				cell.trim().replace(/\*\*/g, "").replace(/\*/g, "").replace(/`/g, "").trim(),
			);

		// The separator row is structure, not data.
		if (cells.every((cell) => SEPARATOR_CELL.test(cell))) continue;

		rows.push(cells.join("\t"));
	}

	return rows.join("\n");
}

/**
 * Does this answer contain a table?
 *
 * @param {string} text the answer
 * @returns {boolean} true when there is one to copy
 */
export function hasTable(text) {
	return String(text || "")
		.split("\n")
		.some((line) => TABLE_ROW.test(line));
}

/**
 * Render a limited markdown subset as HTML.
 *
 * @param {string} text the model's answer
 * @param {object[]} [documents] documents the answer may link to, each a
 *   `{name, url}` pair
 * @returns {string} safe HTML
 */
export function renderMarkdown(text, documents) {
	if (!text) return "";

	const fences = [];
	const codes = [];
	const links = [];
	let html = escapeHtml(text);

	// Fenced code blocks are pulled out before anything else, so that
	// neither the inline rules nor the block rules can touch their
	// contents.
	html = html.replace(/```([\s\S]*?)```/g, (_match, code) => {
		fences.push(code);
		return `~FENCE${fences.length - 1}~`;
	});

	// The documents the assistant read are linked, so that the answer is a
	// doorway into the Desk.  It happens before the blocks are split, so
	// that a name inside a table cell is linked there too.
	if (documents && documents.length) {
		html = linkDocuments(html, documents, links);
	}

	// Split into blocks on blank lines.  A block is a heading, a table, a
	// list or a paragraph.
	const blocks = html.split(/\n{2,}/).filter((block) => block.trim() !== "");

	let rendered = blocks.map((block) => renderBlock(block, codes, links)).join("");

	// The code goes back, with its contents still escaped.
	rendered = rendered.replace(
		/~CODE(\d+)~/g,
		(_match, index) => `<code>${codes[Number(index)]}</code>`,
	);
	rendered = rendered.replace(
		/~FENCE(\d+)~/g,
		(_match, index) => `<pre><code>${fences[Number(index)]}</code></pre>`,
	);

	// The links go back last.  The url is the escaped text it was written
	// as, so it cannot break out of the attribute, and the text is escaped
	// too, so it cannot introduce a tag.  The link opens in a new tab and
	// says so, because the reader's answer is on this page and the link is
	// somewhere else.
	rendered = rendered.replace(/~LINK(\d+)~/g, (_match, index) => {
		const link = links[Number(index)];
		// A link's text was captured before the code was put back, so
		// any code in it is still a placeholder.
		const text = restoreCode(link.text, codes);
		return `<a href="${link.url}" target="_blank" rel="noopener noreferrer">${text}</a>`;
	});

	return rendered;
}
