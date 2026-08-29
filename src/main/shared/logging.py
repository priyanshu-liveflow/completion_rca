"""Structured logging configuration for the project."""

import os
import structlog

_configured = False


def configure_logging(verbose: bool = False, log_file: str = None):
    """Configure structlog. Call from CLI entry points.
    
    Always writes debug-level JSON to a log file (default: .flow_cache/last_run.log).
    Console shows info (or debug if --verbose).
    """
    global _configured
    if _configured:
        return
    _configured = True

    log_path = log_file or os.environ.get("CUA_LOG_FILE") or ".flow_cache/last_run.log"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    _file_handle = open(log_path, "w")

    console_level = structlog.stdlib.NAME_TO_LEVEL["debug" if verbose else "info"]

    def _dual_renderer(logger, method_name, event_dict):
        """Render to file (JSON, all levels) AND console (colored, filtered)."""
        import json as _json
        # Always write to file (all levels including debug)
        _file_handle.write(_json.dumps(event_dict, default=str) + "\n")
        _file_handle.flush()
        # Console: skip debug when not verbose
        level = structlog.stdlib.NAME_TO_LEVEL.get(event_dict.get("level", "info"), 20)
        if level < console_level:
            raise structlog.DropEvent
        renderer = structlog.dev.ConsoleRenderer(colors=True)
        return renderer(logger, method_name, event_dict)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _dual_renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.stdlib.NAME_TO_LEVEL["debug"]
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get a bound logger. Auto-configures if not yet done."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name) if name else structlog.get_logger()
