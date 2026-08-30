"""Ask a model for a unified diff. The only adapter that talks to an LLM.

Consumers type-hint `core.remediation.PatchWriter`, never this class
(spine rule 3).

This adapter is deliberately small and deliberately untrusted. It returns a
string; every decision about whether that string may touch the repository is
made in `core/remediation.py` against the blast radius the *graph* produced.
Nothing here can widen what a patch is allowed to do, which is why it is safe
for the least predictable component in the system to be a model.

Secrets: the request handed to a writer carries source, a claim and failure
output, and nothing else — see `RemediationRequest`. The provider's own
credentials live in the harness environment and are never forwarded into the
prompt or into sandbox execution.
"""

from __future__ import annotations

import asyncio
import re

from src.main.agentradar.core.remediation import RemediationRequest
from src.main.shared.factory import make_provider
from src.main.shared.providers.base import BaseLLMProvider

__all__ = ["LlmPatchWriter", "extract_diff"]

DEFAULT_MAX_SOURCE_CHARS = 6000

_SYSTEM = """\
You repair a single defect in one Python file and output nothing but a patch.

Rules, all of them hard:
- Output a unified diff and no prose, no explanation, no code fences.
- Use the exact form `diff --git a/<path> b/<path>` followed by `---`/`+++`
  and one or more `@@` hunks.
- Touch only the files listed as allowed. A patch touching anything else is
  discarded in full.
- Never edit a test file. The failing test is the specification; changing it
  to pass is the one thing you must not do.
- Make the smallest change that turns the named failing tests green. Do not
  refactor, rename, reformat, or add features.
- If you cannot fix it within these rules, output nothing at all.
"""

# A model asked for "no code fences" produces them anyway often enough that
# stripping them is cheaper than a retry.
_FENCE = re.compile(r"^```[a-zA-Z]*\n|```$", re.MULTILINE)

# The first line that looks like the start of a real diff. Anything a model
# says before it is prose it was told not to write.
_DIFF_START = re.compile(r"^(diff --git |--- )", re.MULTILINE)


def extract_diff(text: str) -> str:
    """Pull the diff out of a model response, or return an empty string.

    Split out from the call so it is testable without a provider, a key or a
    network. Returning `""` rather than raising lets `validate_written_patch`
    turn a garbage response into an ordinary rejection.
    """
    if not text:
        return ""
    cleaned = _FENCE.sub("", text).strip()
    match = _DIFF_START.search(cleaned)
    if match is None:
        return ""
    diff = cleaned[match.start() :].rstrip()
    # `git apply` requires the trailing newline and rejects the patch without
    # it, with an error that reads as a corrupt patch rather than a missing
    # character.
    return diff + "\n"


def build_prompt(
    request: RemediationRequest, *, max_source_chars: int = DEFAULT_MAX_SOURCE_CHARS
) -> str:
    """The whole user message. Explicit about what is allowed, not just asked."""
    tests = "\n".join(f"  {node}" for node in request.failing_tests) or "  (none)"
    allowed = "\n".join(f"  {path}" for path in request.allowed_files) or "  (none)"
    return f"""\
A code reviewer reported this defect, and a test run confirmed it.

REVIEWER'S CLAIM
{request.finding_title}

{request.finding_body}

LOCATION
  file:     {request.file_path}
  function: {request.function_name}

SOURCE OF THE LOCATED FUNCTION
{request.source[:max_source_chars]}

TESTS THAT FAILED
{tests}

FAILURE OUTPUT
{request.failure_excerpt[-2000:]}

FILES YOU MAY TOUCH
{allowed}

Output the unified diff that makes those tests pass. Nothing else.
"""


class LlmPatchWriter:
    """PatchWriter backed by the shared provider factory."""

    def __init__(
        self,
        provider: BaseLLMProvider | None = None,
        *,
        model: str = "",
        max_source_chars: int = DEFAULT_MAX_SOURCE_CHARS,
    ) -> None:
        self._provider = provider if provider is not None else make_provider()
        self._model = model
        self._max_source_chars = max_source_chars

    def write_patch(self, request: RemediationRequest) -> str | None:
        """Return a unified diff, or None when the model declined or rambled.

        `None` and a bad diff are the same outcome downstream — a rejection —
        so a model that cannot follow the format costs one attempt, never a
        bad patch.
        """
        prompt = build_prompt(request, max_source_chars=self._max_source_chars)
        response = asyncio.run(
            self._provider.invoke(
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                system=_SYSTEM,
                model_override=self._model,
            )
        )
        return extract_diff(response.content) or None
