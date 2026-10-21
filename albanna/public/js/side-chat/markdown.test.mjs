import assert from "node:assert";
import { escapeHtml, renderMarkdown } from "./markdown.js";

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

// Empty input.
assert.equal(renderMarkdown(""), "");
assert.equal(renderMarkdown(null), "");

console.log("markdown: all assertions passed");
