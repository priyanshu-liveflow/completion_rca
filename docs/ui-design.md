# AgentRadar UI — design spec

Prototype: https://claude.ai/code/artifact/2d364f6d-2b35-430c-b3c3-10fc51a27439

Build against this. Every visual decision below is already implemented in the prototype — lift the
CSS wholesale rather than re-deriving it.

---

## Direction

**Amber-phosphor instrumentation.** The product doesn't opine, it measures: red test, green test.
So the interface reads as lab equipment, not a SaaS dashboard.

Cool ink-blue ground with a warm instrument-amber accent. The complementary tension gives us the
terminal register without landing on near-black-plus-acid-green, which is where every agent UI ends
up. Amber is reserved for **attention and waiting** — never decoration. When the interface is amber,
it wants something from you.

Measurements in mono, reasoning in serif. That split is the whole typographic idea: telemetry,
paths, and commands are machine output; the "why does this break" column is a human sentence. A lab
notebook, not a log viewer.

---

## Tokens

Dark-first. Bare `:root` is dark; light is redefined under both
`@media (prefers-color-scheme: light)` guarded as `:root:not([data-theme="dark"])` **and**
`:root[data-theme="light"]`. Never declare a color only inside a media block.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--ground` | `#0B1014` | `#E7EDEF` | page |
| `--surface` | `#111A20` | `#F4F8F9` | cards |
| `--raised` | `#16232B` | `#FBFDFD` | card headers, footers |
| `--rule` | `#1E313B` | `#C3D2D8` | borders, the trace line |
| `--ink` | `#D6E4EA` | `#121D24` | primary text |
| `--ink-dim` | `#8AA1AC` | `#41585F` | secondary |
| `--ink-faint` | `#5C7480` | `#6E858E` | timestamps, labels |
| `--amber` | `#F0A030` | `#9A5A00` | **attention / waiting only** |
| `--brk` | `#E85F5A` | `#A9322E` | breaking |
| `--safe` | `#4FB286` | `#1B6E4C` | safe / passing |
| `--review` | `#6E93A8` | `#37606F` | needs review |

Semantic trio (`brk` / `safe` / `review`) is deliberately separate from the accent. A red row is
red because the test failed, not because we wanted contrast.

**Type**

```css
--mono: ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;  /* display + data */
--serif: Charter,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;  /* reasoning */
```

System stacks only — the Artifact CSP blocks font CDNs and inlining a face as a data URI isn't worth
the weight. Labels are mono uppercase 10.5px at `.14em`. Anything with digits in a column gets
`font-variant-numeric: tabular-nums`.

---

## Layout

Single feed column, max 940px. Three-column grid per row: `62px | 22px | 1fr` —
timestamp, dot, content. A 1px **trace line** runs the full height of the feed behind the dot
column, and its gradient shifts by phase (red during reproduce, green during verify, amber during
act). That's the one piece of ambient state.

Structured artifacts interrupt the stream as inset cards spanning only the content column, so the
trace line stays continuous past them.

**Phase strip** in the sticky header — 7 segments, `watch locate blast reproduce patch verify act`,
each a top border that fills as it completes. This is what recovers the "where are we" that a pure
narrative feed loses. Don't skip it.

---

## Components

| Component | Purpose | Notes |
|---|---|---|
| `.ev` | one feed line | modifiers `.hit` (agent action), `.bad`, `.good`, `.sub` (indented tool call) |
| `.pdiv` | phase divider | uppercase, tracked, with a trailing rule |
| `.card` | inset artifact | header + body, `--surface` on `--rule` |
| `.tbl` | impact table | `loc` mono / `pill` verdict / `why` **serif** |
| `.term` | sandbox output | `.cmd` prefixed `$`, `.f` fail, `.p` pass, `.tb` traceback |
| `.result` | run summary bar | `.bad` / `.good` tinted, duration right-aligned |
| `.diff` | proposed patch | `.del` / `.add` / `.ctx` / `.fn` |
| `.heal` | scraper self-repair | amber-bordered card, before/after coverage bars |
| `.gate` | **approval** | amber border, pulsing dot, action list, guard note |
| `.done` | terminal verdict | left rule, serif conclusion + links |

---

## Event bindings

Track B builds entirely against `fixtures/`. This table is the contract — freeze it at H0.

| TrueForge event | Renders |
|---|---|
| `turn.created` | mission header, clock starts |
| `thread.created` | `.ev.hit` — "spawned *agent* ×N" |
| `thread.done` | `.ev` completion line |
| `model.message.delta` | conductor reasoning line |
| `tool.response` · `save_impact` | append row to `.tbl` |
| `tool.response` · `run_collector` (degraded) | `.heal` card, before-coverage bar |
| `tool.response` · `heal_collector` | append after-coverage bar to the same card |
| `tool.response` · `run_tests` | stream `.term` lines, then `.result` |
| `tool.response` · `save_patch` | `.diff` card |
| `tool.approval_required` | **`.gate`** — feed stops here |
| `user.tool_approval` | `.done` card, phase strip completes |
| `sandbox.created` | card meta "sandbox · local" |
| `turn.done` | clock freezes with final elapsed |

Phase transitions aren't a TrueForge event — derive them from which tool fired. Keep that mapping in
one function.

---

## Rules that aren't negotiable

1. **Amber means waiting.** If nothing needs you, nothing is amber. The gate is the only element
   that pulses.
2. **The gate is a hard stop.** Feed halts, phase strip shows `act` in amber-blocked, and the card
   states plainly that nothing has been written yet. This is the Best UI criterion —
   *asks before the irreversible step* — so it gets the most design attention on the page.
3. **The guard note stays.** "The PR tool stayed locked while tests were red" is the sentence that
   explains why this isn't a chatbot. It's copy, but it's load-bearing.
4. **Static verdicts are labelled as such.** The impact table footer reads
   *"static analysis — not yet proven"* until the sandbox runs. Claiming proof before proving it is
   the one way this product is dishonest.
5. **Reasoning is serif, everything else is mono.** Don't let the `why` column drift back to mono
   for consistency's sake — the contrast is the point.

---

## Copy

Terse, lowercase for machine lines, sentence case for human ones. Never "Analyzing…" with an
ellipsis spinner — say what tool is running and against what. Prefer
`get_callers recursive · depth 4` over `Exploring codebase`.

The two lines worth memorising, because they carry the pitch:

- `reproduced — the break is real, not inferred`
- `patch verified — the fix is proven, not proposed`
