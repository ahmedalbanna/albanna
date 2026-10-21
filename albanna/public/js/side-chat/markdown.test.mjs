import assert from "node:assert";
import { escapeHtml, hasTable, renderMarkdown, tableAsTsv } from "./markdown.js";

assert.equal(escapeHtml("<b>&'\"</b>"), "&lt;b&gt;&amp;&#39;&quot;&lt;/b&gt;");

assert.equal(renderMarkdown("**bold**"), "<p><strong>bold</strong></p>");
assert.equal(renderMarkdown("plain"), "<p>plain</p>");

// The whole point: model output cannot introduce markup.
const injected = renderMarkdown('<img src=x onerror="alert(1)">');
assert.ok(!injected.includes("<img"), injected);
assert.ok(injected.includes("&lt;img"), injected);

const script = renderMarkdown("<script>alert(1)</script>");
assert.ok(!script.includes("<script"), script);

// Inline code keeps its asterisks.
assert.ok(
	renderMarkdown("`**not bold**`").includes("<code>**not bold**</code>"),
	renderMarkdown("`**not bold**`"),
);

// A fenced code block keeps its asterisks and its newlines.
const code = renderMarkdown("```\n**raw**\nline two\n```");
assert.ok(code.includes("<pre><code>"), code);
assert.ok(code.includes("**raw**"), code);
assert.ok(code.includes("line two"), code);

// Bullet lists become a list.
const bullets = renderMarkdown("- one\n- two");
assert.ok(bullets.includes("<ul>"), bullets);
assert.ok(bullets.includes("<li>one</li>"), bullets);

// Numbered lists become an ordered list.
const numbered = renderMarkdown("1. one\n2. two");
assert.ok(numbered.includes("<ol>"), numbered);

// A pipe table becomes a table.
const table = renderMarkdown(
	"| Order | Customer | Total |\n|---|---|---|\n| SAL-1 | Acme | 100.00 |\n| SAL-2 | Beta | 200.00 |",
);
assert.ok(table.includes("<table>"), table);
assert.ok(table.includes("<th>Order</th>"), table);
assert.ok(table.includes("<td>Acme</td>"), table);
assert.ok(table.includes("<td>200.00</td>"), table);
assert.ok(!table.includes("|---"), table);

// The table is wrapped in a scroll container: a table wider than the
// panel has to be able to scroll rather than be squeezed into it.
assert.ok(table.includes('<div class="albanna-chat__table-wrap"><table>'), table);
assert.ok(table.includes("</table></div>"), table);

// A table's cells can carry inline formatting.
const boldCell = renderMarkdown("| a | b |\n|---|---|\n| **x** | y |");
assert.ok(boldCell.includes("<td><strong>x</strong></td>"), boldCell);

// A separator written with doubled pipes still parses.
const sloppy = renderMarkdown("| a | b |\n||---|---||\n| 1 | 2 |");
assert.ok(sloppy.includes("<table>"), sloppy);
assert.ok(sloppy.includes("<td>1</td>"), sloppy);

// A heading becomes a heading, and the text after it keeps its place.
const heading = renderMarkdown("## The title\nThe text under it.");
assert.ok(heading.includes("<h3>The title</h3>"), heading);
assert.ok(heading.includes("The text under it."), heading);

const deep = renderMarkdown("### Deeper");
assert.ok(deep.includes("<h4>Deeper</h4>"), deep);

// A heading and its text, with a blank line between them.
const separated = renderMarkdown("# Title\n\nThe text.");
assert.ok(separated.includes("<h2>Title</h2>"), separated);
assert.ok(separated.includes("<p>The text.</p>"), separated);

// A table's cells cannot introduce markup either.
const nasty = renderMarkdown("| a | b |\n|---|---|\n| <script>x</script> | y |");
assert.ok(!nasty.includes("<script"), nasty);

// A nested list stays nested.
const nested = renderMarkdown("- one\n  - one and a half\n- two");
assert.ok(nested.includes("<ul>"), nested);
assert.ok(nested.includes("<li>one<ul><li>one and a half</li></ul></li>"), nested);
assert.ok(nested.includes("<li>two</li>"), nested);

// A wrapped line belongs to the item it continues, not to the list.
const wrapped = renderMarkdown("- the first thing\n  and the rest of it\n- the second thing");
assert.ok(wrapped.includes("the first thing<br>and the rest of it"), wrapped);
assert.ok(!wrapped.includes("and the rest of it</ul>"), wrapped);

// An ordered list is ordered.
const orderedList = renderMarkdown("1. one\n2. two");
assert.ok(orderedList.includes("<ol>"), orderedList);
assert.ok(orderedList.includes("<li>one</li>"), orderedList);

// A blockquote is a blockquote.
const quote = renderMarkdown("> this is a note");
assert.ok(quote.includes("<blockquote>this is a note</blockquote>"), quote);

// A blockquote can carry the inline markup.
const quotedBold = renderMarkdown("> a **bold** note");
assert.ok(quotedBold.includes("<blockquote>a <strong>bold</strong> note</blockquote>"), quotedBold);

// A quote cannot introduce markup.
const quotedNasty = renderMarkdown("> <script>x</script>");
assert.ok(!quotedNasty.includes("<script"), quotedNasty);

// A link becomes a link.
const link = renderMarkdown("See [the report](https://example.com/report).");
assert.ok(link.includes('<a href="https://example.com/report"'), link);
assert.ok(link.includes(">the report</a>"), link);
assert.ok(link.includes('target="_blank"'), link);
assert.ok(link.includes('rel="noopener noreferrer"'), link);

// A link's text is escaped like everything else.
const linkText = renderMarkdown("[<b>x</b>](https://example.com/)");
assert.ok(!linkText.includes("<b>x</b>"), linkText);
assert.ok(linkText.includes("&lt;b&gt;x&lt;/b&gt;"), linkText);

// A url with one level of parentheses survives.
const paren = renderMarkdown("[wiki](https://example.com/Foo_(bar))");
assert.ok(paren.includes('href="https://example.com/Foo_(bar)"'), paren);

// Only http, https and mailto may be linked.  Everything else is left as
// the text it was written as: a link the reader clicks is the one place
// the model's output becomes an action rather than a sentence.
for (const scheme of [
	"javascript:alert(1)",
	"data:text/html,<script>alert(1)</script>",
	"vbscript:msgbox(1)",
	"file:///etc/passwd",
	"/relative/path",
]) {
	const bad = renderMarkdown(`[click](${scheme})`);
	assert.ok(!bad.includes("<a "), `${scheme} -> ${bad}`);
	// It is still there, as the escaped text it was written as.
	assert.ok(bad.includes(escapeHtml(scheme)), `${scheme} -> ${bad}`);
}

// A scheme spelled with an entity is rejected too: the text is escaped
// before the scheme is checked, so it arrives as text and not as a scheme.
const entity = renderMarkdown("[click](&#106;avascript:alert(1))");
assert.ok(!entity.includes("<a "), entity);

// A mailto is allowed.
const mail = renderMarkdown("[write](mailto:someone@example.com)");
assert.ok(mail.includes('<a href="mailto:someone@example.com"'), mail);

// A url cannot break out of the attribute.
const breakout = renderMarkdown('[x](https://example.com/"onmouseover="alert(1))');
assert.ok(!breakout.includes('"onmouseover="alert(1)'), breakout);

// A link inside inline code is code, not a link.
const coded = renderMarkdown("`[not a link](https://example.com/)`");
assert.ok(!coded.includes("<a "), coded);

// A document the assistant read is linked.
const documents = [
	{ name: "SAL-ORD-2026-00012", url: "/app/sales-order/SAL-ORD-2026-00012" },
	{ name: "ACC-SINV-2026-00001", url: "/app/sales-invoice/ACC-SINV-2026-00001" },
];
const linked = renderMarkdown("The order SAL-ORD-2026-00012 is open.", documents);
assert.ok(linked.includes('<a href="/app/sales-order/SAL-ORD-2026-00012"'), linked);
assert.ok(linked.includes(">SAL-ORD-2026-00012</a>"), linked);

// A name that is the beginning of another one is not a link to the
// shorter one: SAL-ORD-2026-0001 is a part of SAL-ORD-2026-00012, not a
// document of its own.
const partial = renderMarkdown("SAL-ORD-2026-00012", [
	{ name: "SAL-ORD-2026-0001", url: "/app/sales-order/SAL-ORD-2026-0001" },
]);
assert.ok(!partial.includes("<a "), partial);

// A name with a word character against it is not a name.
const glued = renderMarkdown("XSAL-ORD-2026-00012X", documents);
assert.ok(!glued.includes("<a "), glued);

// Two names side by side are both linked: the matcher must not swallow
// the character between them.
const twice = renderMarkdown("SAL-ORD-2026-00012 and ACC-SINV-2026-00001", documents);
assert.equal((twice.match(/<a /g) || []).length, 2, twice);

// A name inside a table cell is linked there too.
const inTable = renderMarkdown("| Order |\n|---|\n| SAL-ORD-2026-00012 |", documents);
assert.ok(inTable.includes('<a href="/app/sales-order/SAL-ORD-2026-00012"'), inTable);

// A document the assistant never read is not a link, however much it
// looks like one.
const unknown = renderMarkdown("SAL-ORD-2026-00099", documents);
assert.ok(!unknown.includes("<a "), unknown);

// A table can be taken away as data.
const tsv = tableAsTsv(
	"| Order | Customer | Total |\n|---|---|---|\n| SAL-1 | Acme | 100.00 |\n| SAL-2 | Beta | 200.00 |",
);
assert.equal(tsv, "Order\tCustomer\tTotal\nSAL-1\tAcme\t100.00\nSAL-2\tBeta\t200.00");

// The separator row is structure, not data.
assert.equal(tableAsTsv("| a | b |\n|---|---|\n| 1 | 2 |"), "a\tb\n1\t2");

// The markdown is not data: a spreadsheet reading "**24**" is reading the
// emphasis, not the number.
assert.equal(tableAsTsv("| a | b |\n|---|---|\n| **24** | `x` |"), "a\tb\n24\tx");

// Only the first table is taken.
assert.equal(tableAsTsv("| a |\n|---|\n| 1 |\n\ntext\n\n| b |\n|---|\n| 2 |"), "a\n1");

// An answer with no table has none to take.
assert.equal(tableAsTsv("just a sentence"), "");
assert.equal(hasTable("just a sentence"), false);
assert.equal(hasTable("| a |\n|---|\n| 1 |"), true);

// Empty input.
assert.equal(renderMarkdown(""), "");
assert.equal(renderMarkdown(null), "");

console.log("markdown: all assertions passed");
