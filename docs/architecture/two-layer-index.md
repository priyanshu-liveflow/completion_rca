# Two-Layer Index: Committed vs Local

## Problem
Summarization + embedding is expensive (hours for large repos). Local uncommitted changes shouldn't corrupt the stable index. If user reverts, we'd waste hours re-generating.

## Design

```
.flow_cache/{repo}/
├── semantic_index/
│   ├── committed/              # Built from HEAD commit (stable)
│   │   ├── embeddings.npy
│   │   ├── fids.npy
│   │   ├── names.txt
│   │   ├── chunks.txt
│   │   └── commit.txt         # Commit hash this was built from
│   └── local/                  # Overlay for dirty working tree (small)
│       ├── embeddings.npy      # Only changed functions
│       ├── fids.npy
│       ├── names.txt
│       └── chunks.txt
│
├── summary_index/
│   ├── committed/
│   │   ├── embeddings.npy
│   │   ├── fids.npy
│   │   ├── names.txt
│   │   ├── summaries.txt
│   │   ├── checkpoint.json
│   │   └── commit.txt
│   └── local/
│       ├── embeddings.npy
│       ├── fids.npy
│       ├── names.txt
│       └── summaries.txt
```

## Rules

1. `uv run cua-analyzer index` → builds committed/ from HEAD
2. `uv run cua-analyzer summarize` → builds committed/ summaries from HEAD
3. If working tree is dirty (uncommitted changes):
   - Detect changed functions via `git diff --name-only`
   - Re-extract + re-embed only those into local/
   - local/ is always small (5-50 functions typically)
4. At search time:
   - Load committed/ as base
   - Load local/ as overlay
   - For same fid: local wins (newer source)
   - Merge results from both layers
5. On `git push` (or when HEAD changes to include local changes):
   - Merge local/ into committed/
   - Delete local/
   - Update commit.txt

## Search Logic (pseudocode)

```python
def search(repo, query, top_k):
    # Load both layers
    committed_emb = load(committed/embeddings.npy)
    committed_fids = load(committed/fids.npy)
    
    local_emb = load(local/embeddings.npy)  # may not exist
    local_fids = load(local/fids.npy)
    
    # Score both
    q = embed(query)
    committed_scores = committed_emb @ q
    local_scores = local_emb @ q if local_emb else []
    
    # Merge: local overrides committed for same fid
    results = {}
    for idx, fid in enumerate(committed_fids):
        if fid not in local_fids_set:  # not overridden
            results[fid] = committed_scores[idx]
    for idx, fid in enumerate(local_fids):
        results[fid] = local_scores[idx]  # always wins
    
    return top_k(results)
```

## Merge Logic (on push/commit change)

```python
def merge_local_to_committed(repo):
    # Load both
    committed = load_index(committed/)
    local = load_index(local/)
    
    # Replace committed entries for fids that exist in local
    for fid in local.fids:
        idx = find(committed.fids, fid)
        if idx:
            committed.embeddings[idx] = local.embeddings[fid_idx]
            committed.names[idx] = local.names[fid_idx]
            # etc
        else:
            # New function: append
            committed.append(local[fid])
    
    # Save merged committed/
    save(committed/)
    
    # Clear local/
    rm(local/)
    
    # Update commit hash
    write(committed/commit.txt, current_HEAD)
```

## Detecting Dirty Functions

```python
def get_dirty_fids(repo_path, repo_name):
    # Get modified files from git
    modified = git diff --name-only HEAD  (staged + unstaged)
    
    # For each modified file: extract functions, compare hashes
    # Only functions whose source changed need re-indexing
    # This is fast: just AST parse the changed files
```

## Implementation Order
1. Restructure existing flat layout → committed/ subfolder (migration)
2. Add dirty detection (git diff → changed files → changed functions)
3. Build local/ overlay on index/summarize when dirty
4. Update search to merge both layers
5. Add merge-on-push (detect HEAD change → merge local → committed)
