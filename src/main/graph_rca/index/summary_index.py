"""Summary index — LLM-generated function summaries embedded with MiniLM.

Tiered approach:
  <400 words → qwen2.5-coder:0.5b (fast, good for small/medium)
  ≥400 words → qwen2.5-coder:1.5b (captures domain logic in large functions)

Large functions use head+tail truncation to fit context window.
"""
from __future__ import annotations

import time
import numpy as np
import httpx
from pathlib import Path
from dataclasses import dataclass

from ..store import repo_dir
from src.main.shared.logging import get_logger

log = get_logger("summary_index")

_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"  # only used in build (not search)
_SMALL_MODEL = "qwen2.5-coder:0.5b"
_LARGE_MODEL = "qwen2.5-coder:1.5b"
_WORD_THRESHOLD = 400  # functions with ≥ this many words use the large model
_MIN_WORDS = 5  # skip truly empty functions (blank source)
_MIN_SUMMARY_WORDS = 20  # minimum words in output for substantial functions
_MIN_SUMMARY_WORDS_SHORT = 5  # minimum for short source (<30 words) — getters/setters
_OLLAMA_URL = "http://localhost:11434/api/chat"
_PROMPT_SMALL = "What does this function do and how? Answer with: [PURPOSE] one sentence, then [MECHANISM] how it achieves its goal (key steps, patterns, lookups, config keys used), then [TOUCHES] comma-list of fields/objects modified or read.\n```\n{source}\n```"

_PROMPT_LARGE = "What does this function do and how? Answer with: [PURPOSE] one sentence, then [MECHANISM] describe the key steps and patterns (e.g. template resolution, config lookups, fallback chains, retry logic, delegation to other services), then [TOUCHES] comma-list of fields/objects modified, then [FAILURES] comma-list of what can go wrong.\n```\n{source}\n```"


@dataclass
class SummaryHit:
    fid: int
    name: str
    score: float
    summary: str


def _truncate_for_model(source: str, word_count: int, model: str) -> str:
    """Truncate source to stay within model context budget.
    
    Context budgets (conservative, leaving room for prompt + output):
      0.5b: ~2000 words safe input
      1.5b: ~4500 words safe input (head+tail for anything bigger)
    """
    words = source.split()
    if model == _LARGE_MODEL:
        if word_count > 4500:
            # Monster functions: first 3000 + last 1500 words
            return ' '.join(words[:3000]) + "\n// ... middle omitted ...\n" + ' '.join(words[-1500:])
        elif word_count > 900:
            return ' '.join(words[:600]) + "\n...\n" + ' '.join(words[-300:])
        return source
    else:
        if word_count > 2000:
            return ' '.join(words[:2000])
        elif word_count > 500:
            return ' '.join(words[:500])
        return source





def _is_bad_summary(text: str, source_words: int = 100) -> bool:
    """Detect garbage output: code blocks, JSON errors, or below min word count.
    
    Short source functions (getters/setters <30 words) get a lower threshold.
    """
    if not text:
        return True
    min_words = _MIN_SUMMARY_WORDS_SHORT if source_words < 30 else _MIN_SUMMARY_WORDS
    if len(text.split()) < min_words:
        return True
    if text.startswith('```'):
        return True
    t = text.lower()
    if '"error"' in t or 'invalid json' in t or 'incomplete' in t or 'provided code snippet' in t:
        return True
    return False


def _summarize_one(source: str, model: str, prompt: str, timeout: float = 60, max_retries: int = 2, source_words: int = 100) -> tuple[str, bool]:
    """Call ollama to summarize. Returns (summary, flagged).
    
    Policy:
    - Up to 3 attempts (initial + 2 retries)
    - If all 3 produce bad output: save the 3rd response as-is, flag=True
    - If any attempt produces good output: return it, flag=False
    - On connection/timeout failure: return empty, flag=False (will retry next run)
    """
    full_prompt = prompt.format(source=source)
    last_result = ""

    for attempt in range(max_retries + 1):
        try:
            p = full_prompt
            if attempt == 1:
                if last_result and len(last_result.split()) < _MIN_SUMMARY_WORDS:
                    p = full_prompt + f"\n\nYour previous response was too short ({len(last_result.split())} words). Please provide a more verbose answer with at least 20 words describing what this function does."
                else:
                    p = full_prompt + "\n\nRespond in plain English only. No code blocks, no JSON, no markdown. At least 20 words."
            elif attempt >= 2:
                source_text = full_prompt.split("```")[1] if "```" in full_prompt else full_prompt
                p = f"In plain English (minimum 20 words), finish this sentence: 'This function'\n\nContext:\n{source_text}"

            resp = httpx.post(_OLLAMA_URL, json={
                "model": model,
                "messages": [{"role": "user", "content": p}],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.0, "num_predict": 400 if model == _LARGE_MODEL else 200}
            }, timeout=timeout)
            result = resp.json().get("message", {}).get("content", "").strip()
            last_result = result

            if result and not _is_bad_summary(result, source_words):
                return result, False  # good output
            if attempt < max_retries:
                log.debug("bad_output_retry", attempt=attempt + 1, preview=result[:60])
                continue
        except httpx.TimeoutException:
            if attempt < max_retries:
                time.sleep(1)
            else:
                log.warning("summarize_timeout", model=model)
                return "", False  # infra failure, not flagged
        except httpx.ConnectError:
            if attempt < max_retries:
                time.sleep(3)
            else:
                log.warning("summarize_connect_failed", model=model)
                return "", False
        except Exception as e:
            log.warning("summarize_failed", error=str(e)[:80])
            return "", False

    # All 3 attempts produced bad output — save 3rd response, flag it
    if last_result:
        return last_result, True  # flagged dirty data
    return "", False


def _get_repo_metadata(repo: str) -> dict:
    """Get commit hash, branch, timestamp for metadata."""
    import subprocess
    from ..store import repo_dir as _repo_dir
    from pathlib import Path

    # Try to find the actual repo path from .flow_cache meta
    meta_path = _repo_dir(repo) / "meta.json"
    repo_path = None
    if meta_path.exists():
        import json
        meta = json.loads(meta_path.read_text())
        repo_path = meta.get("repo_path")

    commit, branch = "", ""
    if repo_path and Path(repo_path).exists():
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path,
                                    capture_output=True, text=True, timeout=5).stdout.strip()
            branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo_path,
                                    capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            pass
    return {"commit": commit, "branch": branch}


def _source_hash(source: str) -> str:
    """Quick hash of function source for change detection."""
    import hashlib
    return hashlib.md5(source.encode()).hexdigest()[:12]


def _load_checkpoint(repo: str) -> dict[int, str]:
    """Load checkpoint: {fid: source_hash} of already-processed functions."""
    cp_path = repo_dir(repo) / "summary_index" / "checkpoint.json"
    if not cp_path.exists():
        return {}
    import json
    return json.loads(cp_path.read_text())


def _save_checkpoint(repo: str, processed: dict[int, str], summaries: list[tuple[int, str, str]]):
    """Save checkpoint: processed hashes + partial summaries."""
    import json
    out_dir = repo_dir(repo) / "summary_index"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "checkpoint.json").write_text(json.dumps(processed))
    # Save partial summaries so we don't lose work
    (out_dir / "partial_summaries.json").write_text(
        json.dumps([(fid, name, summary) for fid, name, summary in summaries])
    )


def _load_partial_summaries(repo: str) -> list[tuple[int, str, str]]:
    """Load partial summaries from checkpoint."""
    import json
    p = repo_dir(repo) / "summary_index" / "partial_summaries.json"
    if not p.exists():
        return []
    return [(r[0], r[1], r[2]) for r in json.loads(p.read_text())]


def build_summary_index(
    repo: str,
    functions: list[tuple[int, str, str]] | None = None,
    verbose: bool = False,
) -> dict:
    """Build summary index for a repo with checkpointing and resumption.

    Args:
        repo: repo name (used for cache paths)
        functions: list of (fid, name, source) — if None, loads from semantic index chunks
        verbose: print progress

    Returns:
        stats dict
    """
    from datetime import datetime, timezone
    import json

    if functions is None:
        functions = _load_functions_from_semantic_index(repo)
        if not functions:
            return {"error": "No functions found. Run source semantic index first."}

    # Metadata
    meta = _get_repo_metadata(repo)
    start_time = datetime.now(timezone.utc)
    log.info("summary_index_start_time", time=start_time.isoformat(), commit=meta["commit"][:8] if meta["commit"] else "?", branch=meta["branch"])

    # Load checkpoint — skip already-processed functions with same source hash
    checkpoint = _load_checkpoint(repo)
    existing_summaries = _load_partial_summaries(repo)

    # Detect stale checkpoint: if fids in checkpoint don't exist in current functions, discard them
    current_fids = {fid for fid, _, _ in functions}
    stale_count = sum(1 for fid_str in checkpoint if int(fid_str) not in current_fids)
    if stale_count > len(checkpoint) * 0.3 and len(checkpoint) > 100:
        log.warning("stale_checkpoint_detected", stale=stale_count, total=len(checkpoint),
                    msg="Graph was reindexed. Clearing stale entries from checkpoint.")
        checkpoint = {k: v for k, v in checkpoint.items() if int(k) in current_fids}
        existing_summaries = [(fid, name, s) for fid, name, s in existing_summaries if fid in current_fids]

    # Filter and tier
    small_funcs = []
    large_funcs = []
    skipped_checkpoint = 0

    for fid, name, source in functions:
        word_count = len(source.split())
        if word_count < _MIN_WORDS:
            continue
        # Check checkpoint — skip if source hasn't changed
        src_hash = _source_hash(source)
        if checkpoint.get(str(fid)) == src_hash:
            skipped_checkpoint += 1
            continue
        if word_count >= _WORD_THRESHOLD:
            large_funcs.append((fid, name, source, word_count, src_hash))
        else:
            small_funcs.append((fid, name, source, word_count, src_hash))

    total_new = len(small_funcs) + len(large_funcs)
    log.info("summary_index_plan", total_new=total_new, skipped_checkpoint=skipped_checkpoint,
             small=len(small_funcs), large=len(large_funcs))

    if total_new == 0 and existing_summaries:
        log.info("summary_index_up_to_date")
        return {"status": "up-to-date", "functions_cached": skipped_checkpoint}

    # Start from existing partial summaries
    summaries: list[tuple[int, str, str]] = list(existing_summaries)
    processed: dict[int, str] = dict(checkpoint)
    errors = 0
    flagged_fids: list[dict] = []  # functions where all retries produced bad output
    t_start = time.time()
    checkpoint_interval = 50  # save checkpoint every N functions

    # Small functions with 0.5b
    for i, (fid, name, source, wc, src_hash) in enumerate(small_funcs):
        truncated = _truncate_for_model(source, wc, _SMALL_MODEL)
        summary, is_flagged = _summarize_one(truncated, _SMALL_MODEL, _PROMPT_SMALL, source_words=wc)
        if summary and not is_flagged:
            summaries.append((fid, name, summary))
            processed[str(fid)] = src_hash
        elif summary and is_flagged:
            # Save dirty data but flag it for review
            summaries.append((fid, name, summary))
            processed[str(fid)] = src_hash
            flagged_fids.append({"fid": fid, "name": name, "reason": "3_bad_attempts", "preview": summary[:100]})
        else:
            errors += 1
        if verbose:
            log.debug("summarized", fid=fid, name=name, words=wc, model="0.5b", ok=bool(summary), flagged=is_flagged)
        if (i + 1) % checkpoint_interval == 0:
            _save_checkpoint(repo, processed, summaries)
            elapsed = time.time() - t_start
            rate = (i + 1) / elapsed
            eta = (total_new - i - 1) / rate if rate > 0 else 0
            log.info("checkpoint", done=i + 1, total=total_new, rate=f"{rate:.1f}/s", eta=f"{eta/60:.0f}m", errors=errors, flagged=len(flagged_fids))

    small_done = len(small_funcs)

    # Large functions with 1.5b
    for i, (fid, name, source, wc, src_hash) in enumerate(large_funcs):
        truncated = _truncate_for_model(source, wc, _LARGE_MODEL)
        summary, is_flagged = _summarize_one(truncated, _LARGE_MODEL, _PROMPT_LARGE, timeout=120, source_words=wc)
        if summary and not is_flagged:
            summaries.append((fid, name, summary))
            processed[str(fid)] = src_hash
        elif summary and is_flagged:
            summaries.append((fid, name, summary))
            processed[str(fid)] = src_hash
            flagged_fids.append({"fid": fid, "name": name, "reason": "3_bad_attempts", "preview": summary[:100]})
        else:
            errors += 1
        if verbose:
            log.debug("summarized", fid=fid, name=name, words=wc, model="1.5b", ok=bool(summary), flagged=is_flagged)
        if (i + 1) % checkpoint_interval == 0:
            _save_checkpoint(repo, processed, summaries)
            done_total = small_done + i + 1
            elapsed = time.time() - t_start
            rate = done_total / elapsed
            eta = (total_new - done_total) / rate if rate > 0 else 0
            log.info("checkpoint", done=done_total, total=total_new, rate=f"{rate:.1f}/s", eta=f"{eta/60:.0f}m", errors=errors, flagged=len(flagged_fids))

    elapsed_total = time.time() - t_start
    end_time = datetime.now(timezone.utc)
    log.info("summaries_done", count=len(summaries), errors=errors, flagged=len(flagged_fids),
             time=f"{elapsed_total:.0f}s",
             started=start_time.isoformat(), ended=end_time.isoformat())

    if not summaries and not existing_summaries:
        return {"error": "No summaries generated", "errors": errors}

    # If we have checkpointed functions that were skipped, we need to include them.
    # Rebuild full summary list: re-summarize skipped functions from their stored source.
    # Actually: the summaries list already includes existing_summaries (loaded at start).
    # The issue is when ALL are skipped and existing_summaries was empty (cleaned up).
    # Fix: if summaries is small but checkpoint is large, reload from previous index files.
    if len(summaries) < len(processed) // 2:
        prev_fids_path = repo_dir(repo) / "summary_index" / "fids.npy"
        prev_sums_path = repo_dir(repo) / "summary_index" / "summaries.txt"
        prev_names_path = repo_dir(repo) / "summary_index" / "names.txt"
        if prev_fids_path.exists() and prev_sums_path.exists():
            # Merge: keep existing index entries + add new ones
            prev_fids = set(np.load(prev_fids_path).astype(int))
            prev_summaries = prev_sums_path.read_text().split("\x00")
            prev_names = prev_names_path.read_text().splitlines()
            prev_fids_arr = np.load(prev_fids_path)
            
            # Build lookup of new summaries by fid
            new_fids = {s[0] for s in summaries}
            
            # Add previous entries that aren't in the new batch
            for idx in range(min(len(prev_fids_arr), len(prev_summaries), len(prev_names))):
                fid_val = int(prev_fids_arr[idx])
                if fid_val not in new_fids:
                    summaries.append((fid_val, prev_names[idx], prev_summaries[idx]))
            
            log.info("merged_with_previous", new=len(new_fids), previous=len(prev_fids), total=len(summaries))

    # Embed summaries
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(_EMBED_MODEL_NAME)

    summary_texts = [s[2] for s in summaries]
    log.info("embedding_summaries", count=len(summary_texts))
    embeddings = model.encode(summary_texts, show_progress_bar=True, batch_size=256,
                              normalize_embeddings=True)

    # Save final index
    out_dir = repo_dir(repo) / "summary_index"
    out_dir.mkdir(parents=True, exist_ok=True)

    fids = np.array([s[0] for s in summaries], dtype=np.int64)
    np.save(out_dir / "embeddings.npy", np.array(embeddings, dtype=np.float32))
    np.save(out_dir / "fids.npy", fids)
    (out_dir / "names.txt").write_text("\n".join(s[1] for s in summaries))
    (out_dir / "summaries.txt").write_text("\x00".join(s[2] for s in summaries))

    # Save final checkpoint + metadata
    _save_checkpoint(repo, processed, summaries)
    index_meta = {
        "commit": meta["commit"],
        "branch": meta["branch"],
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "elapsed_seconds": round(elapsed_total),
        "functions_summarized": len(summaries),
        "functions_skipped_checkpoint": skipped_checkpoint,
        "small_model": {"name": _SMALL_MODEL, "count": len(small_funcs)},
        "large_model": {"name": _LARGE_MODEL, "count": len(large_funcs)},
        "errors": errors,
        "flagged": len(flagged_fids),
        "function_hashes": {str(fid): h for fid, h in processed.items()},
    }
    (out_dir / "index_meta.json").write_text(json.dumps(index_meta, indent=2))

    # Save flagged entries for post-run review
    if flagged_fids:
        (out_dir / "flagged.json").write_text(json.dumps(flagged_fids, indent=2))
        log.warning("flagged_summaries", count=len(flagged_fids),
                    path=str(out_dir / "flagged.json"))

    log.info("summary_index_saved", path=str(out_dir), functions=len(summaries))

    # Clean up partial file (complete run)
    partial_path = out_dir / "partial_summaries.json"
    if partial_path.exists():
        partial_path.unlink()

    return {
        "functions_summarized": len(summaries),
        "small_model": len(small_funcs),
        "large_model": len(large_funcs),
        "skipped_checkpoint": skipped_checkpoint,
        "errors": errors,
        "flagged": len(flagged_fids),
        "time_seconds": round(elapsed_total),
    }


def search_summaries(repo: str, query: str, top_k: int = 10) -> list[SummaryHit]:
    """Search function summaries by semantic similarity."""
    idx_dir = repo_dir(repo) / "summary_index"
    if not (idx_dir / "embeddings.npy").exists():
        return []

    embeddings = np.load(idx_dir / "embeddings.npy")
    fids = np.load(idx_dir / "fids.npy")
    names = (idx_dir / "names.txt").read_text().split("\n")
    summaries = (idx_dir / "summaries.txt").read_text().split("\x00")

    from ..store import get_embed_model
    model = get_embed_model()
    q_emb = model.encode([query], normalize_embeddings=True)[0].astype(np.float32)

    scores = embeddings @ q_emb
    top_indices = np.argsort(scores)[::-1]

    seen = set()
    results = []
    for idx in top_indices:
        fid = int(fids[idx])
        if fid in seen:
            continue
        seen.add(fid)
        results.append(SummaryHit(
            fid=fid, name=names[idx],
            score=float(scores[idx]), summary=summaries[idx],
        ))
        if len(results) >= top_k:
            break
    return results


def _split_mechanism(text: str) -> str:
    """Extract mechanism portion from a summary (new or old format)."""
    import re
    # New format: explicit [MECHANISM] section
    m = re.search(r'\[MECHANISM\](.*?)(?:\[TOUCHES\]|\[FAILURES\]|$)', text, re.DOTALL)
    if m:
        return m.group(1).strip()[:500]
    # Old format: everything after first sentence
    match = re.match(r'.*?[.!]\s+(.*)', text, re.DOTALL)
    if match and len(match.group(1)) > 20:
        return match.group(1).strip()[:500]
    return text[:500]


# Cache for mechanism embeddings (built once per repo on first search)
_mechanism_cache: dict[str, tuple[np.ndarray, np.ndarray, list]] = {}


def search_mechanisms(repo: str, query: str, top_k: int = 10) -> list[SummaryHit]:
    """Search function mechanisms (HOW they work) by semantic similarity."""
    global _mechanism_cache

    idx_dir = repo_dir(repo) / "summary_index"
    if not (idx_dir / "embeddings.npy").exists():
        return []

    if repo not in _mechanism_cache:
        fids = np.load(idx_dir / "fids.npy")
        summaries = (idx_dir / "summaries.txt").read_text().split("\x00")
        names = (idx_dir / "names.txt").read_text().split("\n")

        # Extract mechanism text and embed
        mechs = []
        valid_fids = []
        valid_names = []
        for i in range(min(len(fids), len(summaries))):
            text = summaries[i]
            if len(text) < 30:
                continue
            mechs.append(_split_mechanism(text))
            valid_fids.append(int(fids[i]))
            valid_names.append(names[i] if i < len(names) else "?")

        from ..store import get_embed_model
        model = get_embed_model()
        mech_embs = model.encode(mechs, batch_size=256, show_progress_bar=False, normalize_embeddings=True)
        _mechanism_cache[repo] = (mech_embs, np.array(valid_fids), valid_names)
        log.info("mechanism_index_built", repo=repo, functions=len(valid_fids))

    mech_embs, fids_arr, names_list = _mechanism_cache[repo]

    from ..store import get_embed_model
    model = get_embed_model()
    q_emb = model.encode([query], normalize_embeddings=True)[0].astype(np.float32)

    scores = mech_embs @ q_emb
    top_indices = np.argsort(scores)[::-1]

    seen = set()
    results = []
    for idx in top_indices:
        fid = int(fids_arr[idx])
        if fid in seen:
            continue
        seen.add(fid)
        results.append(SummaryHit(fid=fid, name=names_list[idx], score=float(scores[idx]), summary=""))
        if len(results) >= top_k:
            break
    return results


def _load_functions_from_semantic_index(repo: str) -> list[tuple[int, str, str]]:
    """Load (fid, name, full_source) from semantic index chunks, reconstructed."""
    idx_dir = repo_dir(repo) / "semantic_index"
    if not (idx_dir / "fids.npy").exists():
        return []

    fids = np.load(idx_dir / "fids.npy")
    names = (idx_dir / "names.txt").read_text().split("\n")
    chunks = (idx_dir / "chunks.txt").read_text().split("\x00")

    # Reconstruct full source per fid
    from collections import defaultdict
    by_fid: dict[int, list[str]] = defaultdict(list)
    fid_name: dict[int, str] = {}
    for fid_val, name, chunk in zip(fids, names, chunks):
        fid_val = int(fid_val)
        by_fid[fid_val].append(chunk)
        fid_name[fid_val] = name

    return [(fid, fid_name[fid], ' '.join(cks)) for fid, cks in by_fid.items()]


_summary_cache: dict[str, dict[int, str]] = {}


def get_summary_by_fid(repo: str, fid: int) -> str:
    """Direct fid→summary lookup. No semantic search, no mismatches."""
    if repo not in _summary_cache:
        idx_dir = repo_dir(repo) / "summary_index"
        if not (idx_dir / "fids.npy").exists():
            return ""
        fids_arr = np.load(idx_dir / "fids.npy").astype(int)
        texts = (idx_dir / "summaries.txt").read_text().split("\x00")
        _summary_cache[repo] = {int(fids_arr[i]): texts[i] for i in range(min(len(fids_arr), len(texts)))}
    return _summary_cache[repo].get(fid, "")
