# Impact analysis — LOCATE and BLAST

Goal: turn "version X of dependency D is releasing" into a specific, bounded
list of places in *this* repo that might care, and how confident you are in
each — before anything runs.

## Procedure

1. **Locate.** Call `find_contact_points` with the dependency's symbol (a
   class, function, or import name the release notes point at) and the repo
   key. This searches both function names and source text, so it catches a
   bare `import` as well as a call.
2. **Walk the blast radius.** For each contact point, find what depends on
   it:
   - If `select_tests` is registered, call it with the contact points and let
     it run its own strategies (`callers` and `imports`, unioned). Prefer it
     over doing this by hand — it already resolves the module-name-to-file
     join that a manual walk over `get_callers` alone cannot.
   - If `select_tests` is **not** registered, approximate by hand: call
     `get_callers` from each contact point to walk who calls it, and
     `get_call_chain` to see how deep a site sits. Say plainly in your output
     that this is a manual substitute for graph-guided selection, because a
     hand walk over `CALLS` edges alone will not catch an import-shaped
     break — nothing *calls* an import.
3. **Record the strategy.** Whichever path fired — `callers`, `imports`,
   `path`, or a manual approximation — say so explicitly. Never present a
   selection without naming how it was produced. A strategy that quietly
   fell back to something weaker than intended is exactly the kind of thing
   this system exists to surface, not hide.
4. Persist the result with `save_selection` (or `save_impact` per contact
   point, once you have enough to write a row) so the mission record has this
   evidence independent of your final message.

## The rule this file exists to state

**A contact point returned by the graph is a hypothesis, not a verdict.**
`find_contact_points` and `get_callers` tell you where a dependency symbol is
*referenced* — they say nothing about whether the new version actually
breaks that reference. Do not write "broken," "safe," or any outcome word
about a contact point in this step. The only claims you may make here are of
the form "the graph found N references, reached via strategy S" — the
verdict comes from reproduction, later, against a real test run.

If `find_contact_points` returns nothing, say exactly that — zero contact
points found — rather than inventing a plausible-looking site. An empty
result is itself information: either the symbol name is wrong, the repo
is not indexed, or the release genuinely does not touch this codebase.

## Output for this step

A table: contact point (file, function, line if known), which strategy
reached it, and — until reproduction has run — a verdict of `unknown`
for every row. Nothing here is `broken` or `safe` yet.
