# Graph RCA — Remaining Work

## Done (this session)
- [x] Config-driven log parsing (line_pattern, field_map, message_separators)
- [x] Layered config system (base templates + per-repo extends)
- [x] Logger class fallback resolution (tier 2.5)
- [x] Neighbour inference (±3 entries, depth 5 reachability)
- [x] Thread-aware resolution (group_by_thread, per-thread previous_func)
- [x] Stack trace parsing from config (Java + Python)
- [x] Message extraction uses config separators
- [x] Error levels from config
- [x] Staleness check hardened

## TODO
- [ ] Go/Rust stack trace parsing — patterns defined in STACK_PATTERNS, needs implementation in _parse_stack_trace
- [ ] LogEntry persistence to FalkorDB — walkable path stays in-memory, design doc says persist for cross-run caching
- [ ] JIRA enrichment — jira_context passed through pipeline but nothing populates it
- [ ] Tree-sitter for log statement extraction — lite_index uses regex, tree-sitter would be more accurate
- [ ] Multi-service partitioning — config has service_map but preprocessor doesn't split by service before resolution
- [ ] Auto-detect log format — if no config provided, try all base templates and pick best match
- [ ] Continuation pattern matching — config defines them but parse_log_entries only uses entry_start for splitting (continuation_patterns not checked)
