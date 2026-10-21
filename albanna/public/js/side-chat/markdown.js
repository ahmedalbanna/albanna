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

	return `<table>${head}${body}</table>`;
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
 * @returns {string} the block's HTML
 */
function renderInline(block, codes) {
	let html = block.replace(/`([^`\n]+)`/g, (_match, code) => {
		codes.push(code);
		return ` CODE${codes.length - 1} `;
	});

	// Bold, then italic.  Italic is a single `*` on each side and must not
	// match the `**` that bold has already replaced.
	html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
	html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");

	return html;
}

/**
 * Render one block: a heading, a table, a list, or a paragraph.
 *
 * @param {string} block
 * @param {string[]} codes collects the inline code
 * @returns {string} the block's HTML
 */
function renderBlock(block, codes) {
	const lines = block.split("\n");

	// A heading is the first line of a block, and the rest of the block is
	// whatever follows it — a model does not leave a blank line between a
	// heading and its text.
	const heading = lines[0].match(HEADING);
	if (heading) {
		// `#` is the page's title, so the panel's headings start at `h2`.
		const level = Math.min(heading[1].length + 1, 5);
		const rest = lines.slice(1).join("\n");
		const head = `<h${level}>${renderInline(heading[2], codes)}</h${level}>`;
		return rest.trim() ? head + renderBlock(rest, codes) : head;
	}

	// The inline rules run before the table is recognised, so that a cell's
	// `**bold**` is already marked up by the time the row is split.
	const body = renderInline(block, codes);

	if (lines.length >= 2 && TABLE_ROW.test(lines[0]) && isSeparatorRow(lines[1])) {
		return renderTable(body.split("\n"));
	}

	if (/^[ \t]*([-*]|\d+[.)])[ \t]+/.test(lines[0])) {
		const ordered = /^[ \t]*\d+[.)][ \t]+/.test(lines[0]);
		const items = body
			.split("\n")
			.map((line) => line.replace(/^[ \t]*([-*]|\d+[.)])[ \t]+(.*)$/, "<li>$2</li>"))
			.join("");
		return ordered ? `<ol>${items}</ol>` : `<ul>${items}</ul>`;
	}

	return `<p>${body.replace(/\n/g, "<br>")}</p>`;
}

/**
 * Render a limited markdown subset as HTML.
 *
 * @param {string} text the model's answer
 * @returns {string} safe HTML
 */
export function renderMarkdown(text) {
	if (!text) return "";

	const fences = [];
	const codes = [];
	let html = escapeHtml(text);

	// Fenced code blocks are pulled out before anything else, so that
	// neither the inline rules nor the block rules can touch their
	// contents.
	html = html.replace(/```([\s\S]*?)```/g, (_match, code) => {
		fences.push(code);
		return ` FENCE${fences.length - 1} `;
	});

	// Split into blocks on blank lines.  A block is a heading, a table, a
	// list or a paragraph.
	const blocks = html.split(/\n{2,}/).filter((block) => block.trim() !== "");

	let rendered = blocks.map((block) => renderBlock(block, codes)).join("");

	// The code goes back, with its contents still escaped.
	rendered = rendered.replace(
		/ CODE(\d+) /g,
		(_match, index) => `<code>${codes[Number(index)]}</code>`,
	);
	rendered = rendered.replace(
		/ FENCE(\d+) /g,
		(_match, index) => `<pre><code>${fences[Number(index)]}</code></pre>`,
	);

	return rendered;
}
