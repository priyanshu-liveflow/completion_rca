"""Integration tests for dedup policy, context builder dispatch, and tiering."""
import pytest
from dataclasses import field
from unittest.mock import patch, MagicMock

from src.main.graph_rca.models import LogEntry, WalkablePath
from src.main.graph_rca.preprocess.chunked import _dedup_entries
from src.main.graph_rca.decompose import AgentAssignment
from src.main.graph_rca.trace_context_builder import (
    build_agent_contexts, FunctionValidation, AgentContext,
)


def _entry(line, level="INFO", static_text="msg", originated_from=None, originated_from_ids=None, stack_trace=None):
    return LogEntry(
        line_number=line, line_end=line, raw_text=f"raw {line}",
        level=level, timestamp=None, static_text=static_text,
        dynamic_values=[], service=None, thread_id=None, stack_trace=stack_trace,
        originated_from=originated_from or [], originated_from_ids=originated_from_ids or [],
        is_error=level in ("ERROR", "FATAL", "SEVERE"),
    )


# ============================================================
# DEDUP POLICY
# ============================================================

class TestDedupPolicy:
    def test_info_deduped_with_repeat_count(self):
        entries = [_entry(i, "INFO", "same message") for i in range(5)]
        result = _dedup_entries(entries)
        assert len(result) == 1
        assert result[0].repeat_count == 5

    def test_error_never_deduped(self):
        entries = [_entry(i, "ERROR", "NPE at line 42") for i in range(4)]
        result = _dedup_entries(entries)
        assert len(result) == 4

    def test_warn_never_deduped(self):
        entries = [_entry(i, "WARN", "connection timeout") for i in range(3)]
        result = _dedup_entries(entries)
        assert len(result) == 3

    def test_mixed_levels_correct_behavior(self):
        entries = [
            _entry(1, "INFO", "starting job"),
            _entry(2, "INFO", "starting job"),
            _entry(3, "ERROR", "failed"),
            _entry(4, "ERROR", "failed"),
            _entry(5, "DEBUG", "cache hit"),
            _entry(6, "DEBUG", "cache hit"),
            _entry(7, "DEBUG", "cache hit"),
        ]
        result = _dedup_entries(entries)
        infos = [e for e in result if e.level == "INFO"]
        errors = [e for e in result if e.level == "ERROR"]
        debugs = [e for e in result if e.level == "DEBUG"]
        assert len(infos) == 1
        assert infos[0].repeat_count == 2
        assert len(errors) == 2
        assert len(debugs) == 1
        assert debugs[0].repeat_count == 3

    def test_different_info_messages_not_deduped(self):
        entries = [
            _entry(1, "INFO", "message A"),
            _entry(2, "INFO", "message B"),
            _entry(3, "INFO", "message A"),
        ]
        result = _dedup_entries(entries)
        assert len(result) == 2
        a = next(e for e in result if "A" in e.static_text)
        assert a.repeat_count == 2

    def test_timestamps_stripped_from_signature(self):
        """Entries differing only in timestamps/hex/numbers should dedup."""
        entries = [
            _entry(1, "INFO", "request id=abc123 at 2024-01-01T10:00:00Z took 500ms"),
            _entry(2, "INFO", "request id=def456 at 2024-01-02T11:00:00Z took 300ms"),
        ]
        result = _dedup_entries(entries)
        assert len(result) == 1
        assert result[0].repeat_count == 2


# ============================================================
# CONTEXT BUILDER DISPATCH
# ============================================================

class TestContextBuilderDispatch:
    """Test that build_agent_contexts correctly dispatches or drops agents."""

    def _make_path(self, entries, error_points=None):
        """Build a minimal WalkablePath."""
        path = WalkablePath(
            entries=entries,
            branches=[],
            error_points=error_points or [i for i, e in enumerate(entries) if e.is_error],
            coverage_pct=80.0,
            service="test-service",
            repo="test-repo",
        )
        # Build fid_to_entries mapping
        path.fid_to_entries = {}
        for i, e in enumerate(entries):
            for fid in e.originated_from_ids:
                path.fid_to_entries.setdefault(fid, []).append(i)
        return path

    @patch("src.main.graph_rca.trace_context_builder.FunctionValidator")
    @patch("src.main.graph_rca.trace_context_builder.load_merged_flow")
    def test_agent_dropped_when_no_owned_errors(self, mock_merged, mock_validator_cls):
        """Default mode agent with 0 owned errors should be dropped."""
        entries = [_entry(1, "INFO", "ok", originated_from_ids=[100])]
        path = self._make_path(entries, error_points=[])

        mock_validator = MagicMock()
        mock_validator.validate.return_value = FunctionValidation(
            name="someFunc", fid=999, found=True, source="def someFunc() {}",
            strategy="exact", ambiguous=False,
        )
        mock_validator.get_source.return_value = "def someFunc() {}"
        mock_validator.get_flow_graph.return_value = ""
        mock_validator.get_callers_callees.return_value = ([], [])
        mock_validator_cls.return_value = mock_validator
        mock_merged.return_value = None

        assignment = AgentAssignment(
            id="test_1", starting_node="someFunc", scope="test",
            direction="backward", model="default", tools="graph_only",
        )
        contexts = build_agent_contexts([assignment], path, "test-repo")
        assert len(contexts) == 0

    @patch("src.main.graph_rca.trace_context_builder.FunctionValidator")
    @patch("src.main.graph_rca.trace_context_builder.load_merged_flow")
    def test_absence_agent_dispatched_without_errors(self, mock_merged, mock_validator_cls):
        """Absence mode agent should dispatch even with 0 owned errors."""
        entries = [_entry(1, "INFO", "ok", originated_from_ids=[100])]
        path = self._make_path(entries, error_points=[])

        mock_validator = MagicMock()
        mock_validator.validate.return_value = FunctionValidation(
            name="missingFunc", fid=888, found=True, source="def missingFunc() {}",
            strategy="exact", ambiguous=False,
        )
        mock_validator.get_source.return_value = "def missingFunc() {}"
        mock_validator.get_flow_graph.return_value = ""
        mock_validator.get_callers_callees.return_value = ([], [])
        mock_validator_cls.return_value = mock_validator
        mock_merged.return_value = {"sequence": [["missingFunc", 10, "INFO", [], "expected log output"]]}

        assignment = AgentAssignment(
            id="absence_1", starting_node="missingFunc", scope="why not called",
            direction="forward", model="default", tools="graph_only",
            context_mode="absence",
        )
        contexts = build_agent_contexts([assignment], path, "test-repo")
        assert len(contexts) == 1
        assert "ABSENCE" in contexts[0].warnings[0]

    @patch("src.main.graph_rca.trace_context_builder.FunctionValidator")
    @patch("src.main.graph_rca.trace_context_builder.load_merged_flow")
    def test_error_agent_dispatched_with_owned_errors(self, mock_merged, mock_validator_cls):
        """Agent owning errors should be dispatched normally."""
        entries = [
            _entry(1, "INFO", "starting", originated_from=["errorFunc"], originated_from_ids=[200]),
            _entry(2, "ERROR", "NPE", originated_from=["errorFunc"], originated_from_ids=[200]),
        ]
        path = self._make_path(entries)

        mock_validator = MagicMock()
        mock_validator.validate.return_value = FunctionValidation(
            name="errorFunc", fid=200, found=True, source="def errorFunc() {}",
            strategy="exact", ambiguous=False,
        )
        mock_validator.get_source.return_value = "def errorFunc() {}"
        mock_validator.get_flow_graph.return_value = ""
        mock_validator.get_callers_callees.return_value = ([], [])
        mock_validator_cls.return_value = mock_validator
        mock_merged.return_value = None

        assignment = AgentAssignment(
            id="error_1", starting_node="errorFunc", scope="investigate NPE",
            direction="backward", model="default", tools="graph_only",
        )
        contexts = build_agent_contexts([assignment], path, "test-repo")
        assert len(contexts) == 1
        assert any("ERROR" in line for line in contexts[0].cluster_entries)


# ============================================================
# SOURCE GREP FALLBACK (get_callers / find_by_pattern)
# ============================================================

class TestSourceGrepFallback:
    """Test that source grep fallback finds callers missed by CALLS edges."""

    @patch("src.main.code_tools.queries.get_graph")
    def test_get_callers_falls_back_to_source_grep(self, mock_get_graph):
        """When CALLS edges return nothing, grep source for references."""
        from src.main.code_tools.queries import get_callers

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # First query (CALLS edges) returns nothing
        # Second query (source grep) finds callers
        mock_graph.query.side_effect = [
            MagicMock(result_set=[]),  # CALLS query
            MagicMock(result_set=[["withComment"], ["buildResponse"]]),  # source grep (_grep returns names only)
        ]

        result = get_callers("addProvisioningComments", "ecmv4-g2")
        assert result == [{"name": "withComment", "fid": None}, {"name": "buildResponse", "fid": None}]
        assert mock_graph.query.call_count == 2

    @patch("src.main.code_tools.queries.get_graph")
    def test_get_callers_uses_calls_edges_first(self, mock_get_graph):
        """When CALLS edges exist, don't fall back to grep."""
        from src.main.code_tools.queries import get_callers

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # CALLS edges return results (now returns [name, id])
        mock_graph.query.return_value = MagicMock(result_set=[["createAccount", 101], ["deleteAccount", 102]])

        result = get_callers("setProvisioningComments", "ecmv4-g2")
        assert result == [{"name": "createAccount", "fid": 101}, {"name": "deleteAccount", "fid": 102}]
        assert mock_graph.query.call_count == 1  # no fallback needed

    @patch("src.main.code_tools.queries.get_graph")
    def test_find_by_pattern_greps_source_when_name_fails(self, mock_get_graph):
        """When name search returns nothing, grep source code."""
        from src.main.code_tools.queries import find_by_pattern

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # Name match returns nothing, source grep finds functions (now returns [name, id])
        mock_graph.query.side_effect = [
            MagicMock(result_set=[]),  # name CONTAINS
            MagicMock(result_set=[["processTasks", 201], ["handleTaskResponse", 202]]),  # source CONTAINS
        ]

        result = find_by_pattern("EntitlementMgmtResponse", "ecmv4-g2")
        assert result == [{"name": "processTasks", "fid": 201}, {"name": "handleTaskResponse", "fid": 202}]
        assert mock_graph.query.call_count == 2

    @patch("src.main.code_tools.queries.get_graph")
    def test_grep_excludes_self(self, mock_get_graph):
        """Source grep should not return the function itself as its own caller."""
        from src.main.code_tools.queries import _grep_source_for_refs

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # Grep returns results including self (should be filtered by query WHERE f.name <> $fname)
        mock_graph.query.return_value = MagicMock(result_set=[["callerFunc"]])

        result = _grep_source_for_refs("addProvisioningComments", "ecmv4-g2", mock_graph)
        assert "addProvisioningComments" not in result
        assert result == ["callerFunc"]

    @patch("src.main.code_tools.queries.get_graph")
    def test_grep_false_positive_substring_match(self, mock_get_graph):
        """Source grep may return false positives from substring matches in comments/strings."""
        from src.main.code_tools.queries import _grep_source_for_refs

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        # Graph returns functions that contain "get" in source — some are false positives
        # (e.g. a function that has "// TODO: implement getProvisioningComments" in a comment)
        # The grep is intentionally broad — false positives are acceptable because:
        # 1. The agent reads the source and determines relevance
        # 2. Better to have false positives than miss real callers (the previous problem)
        mock_graph.query.return_value = MagicMock(result_set=[
            ["realCaller"],
            ["commentMentionsIt"],  # false positive from comment
        ])

        result = _grep_source_for_refs("getProvisioningComments", "ecmv4-g2", mock_graph)
        # Both returned — agent will filter. That's acceptable.
        assert len(result) == 2
        assert "realCaller" in result

    @patch("src.main.code_tools.queries.get_graph")
    def test_get_callers_empty_when_nothing_found(self, mock_get_graph):
        """When both CALLS and grep return nothing, return empty list."""
        from src.main.code_tools.queries import get_callers

        mock_graph = MagicMock()
        mock_get_graph.return_value = mock_graph

        mock_graph.query.side_effect = [
            MagicMock(result_set=[]),  # CALLS
            MagicMock(result_set=[]),  # grep
        ]

        result = get_callers("totallyNonexistentFunction", "ecmv4-g2")
        assert result == []
