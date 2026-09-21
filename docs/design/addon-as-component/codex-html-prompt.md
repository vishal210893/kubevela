# Prompt for Codex: turn the addon-as-component design docs into a polished HTML site

Copy everything below the line into Codex. It converts the three design docs in
this folder into a single, visually appealing static HTML page with a modern UI.

---

## Task

Convert the three design documents in `docs/design/addon-as-component/` (`HLD.md`,
`LLD.md`, and `RESOURCE-TRACKERS.md`) into one self-contained, static HTML file:
`docs/design/addon-as-component/index.html`.

The source is technical design documentation for a KubeVela feature. The output
must be accurate to the source (do not invent or drop content) and pleasant to
read for an engineer.

## Inputs

- `docs/design/addon-as-component/HLD.md` (high-level design)
- `docs/design/addon-as-component/LLD.md` (low-level design)
- `docs/design/addon-as-component/RESOURCE-TRACKERS.md` (ResourceTracker walkthrough)

All three contain Markdown prose, tables, fenced code blocks (Go, YAML, CUE), and
Mermaid diagrams in ```mermaid fences. Preserve all of it.

## Output requirements

Produce ONE file, `index.html`, that opens correctly by double-clicking (no build
step, no local server needed). It may pull CSS/JS from CDNs.

### Structure and navigation

- A single page with three top-level sections, rendered in this order: HLD, LLD,
  and ResourceTrackers. Each becomes a top-level group in the navigation, so a
  reader can jump straight to the ResourceTracker walkthrough.
- A fixed left sidebar (collapsible on narrow screens) with a nested table of
  contents generated from the headings, grouped under those three sections, with
  smooth-scroll anchor links and an active-section highlight that tracks scroll
  position.
- A sticky top bar with the page title ("Addon as Component: Design") and a
  light/dark theme toggle that persists the choice in localStorage.
- A reading-progress bar under the top bar.

### Rendering

- Render the Markdown faithfully (headings, lists, tables, inline code, links).
  You may use `marked` (or similar) from a CDN, or pre-render to HTML. Either way,
  the final file must be self-contained enough to open offline except for CDN
  assets.
- Render every ```mermaid block with Mermaid.js (CDN). Diagrams must re-render on
  theme toggle so they stay legible in both light and dark mode.
- Syntax-highlight Go, YAML, and CUE code blocks (highlight.js or Prism from a
  CDN). Add a copy-to-clipboard button on each code block.
- Render tables as clean, striped, responsive tables.

### Visual design

Aim for a modern, calm, professional look, similar to a good docs site
(Stripe/Linear/Vercel docs sensibility). Concretely:

- A restrained color palette with one accent color. Provide both a light and a
  dark theme with proper contrast (meet WCAG AA, 4.5:1 for body text).
- System font stack for body text, a monospace stack for code. Base body size
  16px, line-height about 1.6, comfortable max content width (around 70 to 80
  characters per line).
- Generous whitespace, subtle borders, soft shadows on cards and code blocks.
  Rounded corners around 8px. No harsh full-black on full-white.
- Callout styling for the tables that compare before/after (the RT-size fix) and
  for the per-ResourceTracker resource tables, so the key numbers stand out. The
  three ownership/flow Mermaid diagrams (HLD architecture, LLD flows, and the
  ResourceTracker ownership map) are the centerpiece; give them room to breathe.
- Anchor links on hover for each heading.
- Respect `prefers-reduced-motion`: no essential information conveyed by motion,
  and animations disabled when the user asks for reduced motion.
- Do not use emoji as icons. If you want icons, use an SVG icon set from a CDN.

### Accessibility and quality

- Semantic HTML: one `h1`, a logical heading hierarchy, `nav` for the TOC,
  `main` for content.
- Keyboard navigable: the TOC, theme toggle, and copy buttons all reachable and
  operable by keyboard, with visible focus rings.
- Diagrams get descriptive `aria-label` or a text caption so they are not the
  only way to get the information.
- No console errors. Degrade gracefully if a CDN fails (content still readable).

## Constraints

- Keep it to the single `index.html` (inline CSS and JS is fine, or small
  sibling assets if you prefer, but one HTML entry point).
- Do not alter the meaning of the source docs. If something in the Markdown is
  ambiguous, render it as written rather than rewriting it.
- No tracking scripts, no analytics, no external fonts that block rendering
  (use `font-display: swap` if you load web fonts, and prefer the system stack).

## Deliverable

`docs/design/addon-as-component/index.html`, plus a one-paragraph note on which
CDN libraries you used and any fallback behavior. Confirm it opens offline and
that all three sections (HLD, LLD, ResourceTrackers), every Mermaid diagram, and
all code blocks render in both light and dark themes.
