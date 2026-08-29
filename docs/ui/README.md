# UI prototypes

Open any file here directly in a browser — no build step, no dependencies, no network.

| File | What it is |
|---|---|
| `mission-feed.html` | Mission detail view. Plays a full mission: scouts fan out, scraper self-repairs, impact table fills, tests go red, patch applied, tests go green, hard stop at the approval gate. |

Published copy (same file): https://claude.ai/code/artifact/2d364f6d-2b35-430c-b3c3-10fc51a27439

Design rationale, tokens, component inventory, and the event-binding contract live in
[`../ui-design.md`](../ui-design.md).

## How to use these

They are the reference implementation, not a mockup to interpret. The CSS is production-shaped —
tokens up top, three-state theming, no framework. Lift it into `apps/web` rather than re-deriving
it from screenshots.

The playback script is fixture-shaped too: the mission is an array of `[ms, fn]` steps. When real
`fixtures/` land, swap the array for the recorded event stream and the render functions stay as-is.

## Doubles as the demo fallback

If the venue network dies, this file still plays the whole arc offline. Keep it open in a second
tab on demo day.
