# Writing a Repo Config for Graph RCA

This guide walks you through creating a YAML config file for the `code-rca` pipeline. The config tells the parser how to split your log into entries, extract fields (timestamp, thread, level, logger, message), and filter noise.

**Without a config, the parser sees your entire log as 1 entry and analysis fails.**

---

## Quick Start

```bash
cp configs/base/spring-boot.yaml configs/my-repo.yaml
```

Edit `my-repo.yaml`:

```yaml
extends: base/spring-boot.yaml

repo: my-repo-name          # Must match the --name used during indexing
language: groovy             # groovy, java, python, go, rust, javascript, powershell, c
service_name: my-service

skip_judges_if_single_trace: false   # Let full pipeline run even for obvious stack traces
```

Then run:

```bash
uv run graph-rca run --log /path/to/app.log --mode code-rca --repo my-repo-name --config configs/my-repo.yaml --verbose
```

---

## Config Structure

```yaml
extends: base/spring-boot.yaml    # Optional: inherit defaults from a base template

repo: my-repo                     # MUST match the name used in `uv run graph-rca index --name`
language: groovy                  # Primary language of the codebase
service_name: my-service          # Human-friendly service name

log_format:
  entry_start: <regex>            # CRITICAL: splits the log into entries
  line_pattern: <regex>           # PRIMARY: extracts named groups from each entry's first line
  alt_patterns: [<regex>, ...]    # FALLBACK: tried if line_pattern doesn't match
  continuation_patterns: [...]    # Lines that belong to the previous entry (stack traces etc)
  message_separators: [' - ']     # Splits logger from message within the line

ignore_patterns: [...]            # Framework log patterns to skip during resolution
skip_judges_if_single_trace: false
```

---

## The Critical Fields

### `entry_start` — The Most Important Field

This regex determines where one log entry ends and the next begins. **If it doesn't match your log's timestamp format, the entire log becomes 1 entry.**

**How to find it:** Look at the first few lines of your log:

```
# K8s wrapped (ISO timestamp prefix):
2024-01-15T10:30:00.123456Z 2024-01-15 10:30:00,123 [thread] INFO logger - message

# Raw Logback:
2024-01-15 10:30:00,123 [thread] INFO logger - message

# Raw Log4j:
15 Jan 2024 10:30:00,123 INFO [thread] logger - message
```

**Common patterns:**

| Log format | `entry_start` pattern |
|-----------|----------------------|
| K8s ISO prefix | `'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+'` |
| Raw Logback/Log4j | `'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}'` |
| Both (permissive) | `'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'` |
| Syslog | `'^[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}'` |
| Python default | `'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+'` |
| Go structured (JSON) | `'^\{"' ` |

**Gotcha — mixed formats:** If your log has BOTH K8s timestamps AND raw Logback (e.g., startup vs runtime), use the permissive pattern:

```yaml
entry_start: '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'
```

The `[T ]` matches either the `T` in ISO format or the space in Logback format.

**Verification:** After setting entry_start, check the preprocessor output:

```
preprocessed  entries=3370 errors=12
```

If you see `entries=1` from a large log — your pattern is wrong.

---

### `line_pattern` — Field Extraction

A regex with **named groups** that extracts structured fields from each log line. Required groups: `timestamp`, `thread`, `level`, `logger`, `message`.

**Example for Logback default:**
```yaml
line_pattern: '^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+)\s+\[(?P<thread>[^\]]+)\]\s+(?P<level>\w+)\s+(?P<logger>\S+)\s+-\s+(?P<message>.*)'
```

Matches: `2024-01-15 10:30:00,123 [main-thread] INFO com.example.MyService - Starting up`

**Example for K8s prefix + Logback:**
```yaml
line_pattern: '^\S+Z\s+(?P<timestamp>\S+)\s+\[(?P<thread>[^\]]+)\]\s+(?P<level>\w+)\s+(?P<logger>\S+)\s+-\s+(?P<message>.*)'
```

Matches: `2024-01-15T10:30:00.123Z 10:30:00,123 [thread-1] INFO c.e.MyService - message`

**Tips:**
- `(?P<logger>\S+)` — the logger is used to resolve which class emitted the log
- `(?P<message>.*)` — greedy, captures everything after the separator
- If your logger has a prefix like `c.s.e.` (abbreviated), that's fine — the resolver handles it
- If the line has context brackets like `[requestId=abc]`, use non-greedy match: `(?:\[.*?\]\s+-\s+|-\s+)`

---

### `alt_patterns` — Multiple Formats in One Log

Many apps have different log formats during startup vs runtime, or from different libraries. Add alternatives:

```yaml
alt_patterns:
  # Tomcat startup format (date format differs)
  - '^\S+Z\s+\d{2}-\w+-\d{4}\s+(?P<timestamp>\S+)\s+(?P<level>\w+)\s+\[(?P<thread>[^\]]+)\]\s+(?P<logger>\S+)\s+(?P<message>.*)'
  # Raw Logback (no K8s prefix)
  - '^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+)\s+\[(?P<thread>[^\]]+)\]\s+(?P<level>\w+)\s+(?P<logger>\S+)\s+-\s+(?P<message>.*)'
```

The parser tries `line_pattern` first, then each alt in order. First match wins.

---

### `continuation_patterns` — Multi-line Entries

Lines matching these patterns are appended to the previous entry instead of starting a new one:

```yaml
continuation_patterns:
  - '^\s+at\s+'           # Java stack trace frames
  - '^\s+\.\.\.\s+\d+'   # "... 42 more" truncated frames
  - '^Caused by:'         # Chained exceptions
  - '^\s+\^'             # Python error indicator
  - '^\s+File "'         # Python traceback frames
```

**Without these, each stack frame becomes a separate "entry" and resolution breaks.**

---

## `ignore_patterns` — Filtering Framework Noise

Patterns for log entries that come from framework/library code (not your application). These are skipped during resolution to avoid wasting trie lookups on messages you can't trace to your source.

```yaml
ignore_patterns:
  # Spring internals
  - 'org.springframework.*'
  - 'org.apache.catalina.*'
  - 'org.apache.coyote.*'
  
  # JVM/GC
  - 'sun.rmi.*'
  - 'java.lang.ref.*'
  
  # Hibernate SQL logging
  - '^Hibernate:.*'
  
  # Generic framework patterns
  - 'Initializing Spring.*'
  - 'HikariPool.*'
```

**Rules for ignore patterns:**

1. **Verify before adding.** Grep your actual codebase:
   ```bash
   grep -r "the pattern" ~/my-repo/
   ```
   If it's in YOUR code, don't ignore it.

2. **Don't be too broad.** `AutoUser_Request_` might seem like noise but could match actual app functions. Test with a few entries first.

3. **Logger-based patterns are safest.** `'org.springframework.*'` targets the logger class, which is always framework.

4. **Message-based patterns are risky.** `'Error occurred'` might match both framework and app logs.

---

## `skip_judges_if_single_trace`

```yaml
skip_judges_if_single_trace: false    # Recommended
```

When `true` (default), if all errors in the log have obvious stack traces pointing to a single function, the pipeline short-circuits and returns immediately without running trace agents or judges.

Set to `false` to always run the full investigation pipeline. This is recommended because:
- The "obvious" cause might be a symptom, not the root cause
- Connection failures wrapped in parse errors need deeper investigation
- You're paying for analysis anyway — get the full picture

---

## Language Setting

```yaml
language: groovy    # groovy, java, python, go, rust, javascript, powershell, c
```

This controls:
- Which flow patterns YAML is loaded (`configs/flow_patterns/{lang}.yaml`)
- How function boundaries are detected (brace-based vs indent-based)
- Stack trace parsing style (Java vs Python vs Go)

If your project is multi-language, set the **primary** language (the one generating logs).

---

## Base Templates

Inherit common patterns with `extends`:

```yaml
extends: base/spring-boot.yaml    # Spring Boot / Grails / Tomcat
extends: base/python-logging.yaml # Python logging module
extends: base/go-structured.yaml  # Go structured logging (zerolog, zap)
```

Base templates provide default `continuation_patterns`, common `ignore_patterns`, and sensible `entry_start` patterns. Override any field in your repo config to customize.

---

## Debugging Tips

### "entries=1" — Parser sees entire log as one entry

```
preprocessed  entries=1 errors=1
```

**Cause:** `entry_start` doesn't match. Check:
1. Copy the first line of your log
2. Test with Python: `import re; print(bool(re.match(r'your-pattern', first_line)))`
3. Common mistakes:
   - Escaping: YAML single quotes (`'...'`) don't need `\\`, double quotes do
   - Missing `T` vs space: K8s uses `T`, Logback uses space — use `[T ]`
   - Missing milliseconds format: `,\d+` vs `.\d+`

### "coverage_pct=0" — No entries resolved to code

**Causes:**
- `repo` in config doesn't match the indexed name
- Index is stale (run `uv run graph-rca index --repo /path --name name --force`)
- Logger class in log doesn't match source paths (abbreviated loggers)

### High divergences in flow alignment

**Causes:**
- Merge depth too shallow (currently 3, should be 6+)
- Linear alignment on branching code (branch-aware alignment not yet implemented)
- Expected: some divergence is normal; only investigate if >80% entries diverge

---

## Full Example: ecmv4 (Grails on Tomcat, K8s)

```yaml
# configs/ecmv4.yaml
extends: base/spring-boot.yaml

repo: ecmv4-g2
language: groovy
service_name: ecm

skip_judges_if_single_trace: false

log_format:
  # Permissive: matches both K8s ISO and raw Logback
  entry_start: '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'
  # K8s prefix + Logback pattern
  line_pattern: '^\S+Z\s+(?P<timestamp>\S+)\s+\[(?P<thread>[^\]]+)\]\s+(?P<level>\w+)\s+(?P<logger>\S+)\s+-\s+(?:\[.*?\]\s+-\s+|-\s+)?(?P<message>.*)'
  alt_patterns:
    # Tomcat startup format
    - '^\S+Z\s+\d{2}-\w+-\d{4}\s+(?P<timestamp>\S+)\s+(?P<level>\w+)\s+\[(?P<thread>[^\]]+)\]\s+(?P<logger>\S+)\s+(?P<message>.*)'
    # Raw Logback (local dev, no K8s)
    - '^(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+)\s+\[(?P<thread>[^\]]+)\]\s+(?P<level>\w+)\s+(?P<logger>\S+)\s+-\s+(?P<message>.*)'
  continuation_patterns:
    - '^\s+at\s+'
    - '^\s+\.\.\.\s+\d+'
    - '^Caused by:'
    - '^\t'

ignore_patterns:
  # Spring/Tomcat framework
  - 'org.springframework.*'
  - 'org.apache.catalina.*'
  - 'org.apache.coyote.*'
  - 'org.apache.tomcat.*'
  - 'org.hibernate.*'
  # ... (70+ verified patterns for ecmv4)
```

**Results with this config:**
- 3370 entries parsed from 353MB log
- 84% resolution (2840 entries mapped to source functions)
- 6s resolve time via FragmentTrie

---

## Checklist

Before running `code-rca`:

- [ ] `repo` matches the `--name` used during indexing
- [ ] `entry_start` tested against first 5 lines of your log
- [ ] `line_pattern` has all 5 named groups: `timestamp`, `thread`, `level`, `logger`, `message`
- [ ] `continuation_patterns` includes stack trace patterns for your language
- [ ] Index is fresh (`uv run graph-rca index --repo /path --name name`)
- [ ] FalkorDB is running (`redis-cli -s ~/.codegraphcontext/global/db/falkordb.sock PING`)
