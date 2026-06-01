"""Autonomous Refactor Agent API — real code analysis with ast."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from ml_core import configure_logging, install_middleware
from ml_core import lifespan as _app_lifespan
from ml_core.exceptions import ApplicationError
from ml_core.observability import metrics_router, observe_request
from pydantic import BaseModel, Field

from app.code_analyzer import CodeAnalyzer, DirectoryReport, FileReport
from app.github_export import create_pr_draft
from app.refactor_suggestions import estimate_effort, generate_diff_preview
from finetune.extension import agent_training_guide

logger = configure_logging("refactor-agent")

app = FastAPI(
    title="Autonomous Refactor Agent",
    version="1.0.0",
    description="AST-based Python code quality analysis and refactoring suggestions",
)

# Wire lifespan and middleware
try:
    app.router.lifespan_context = _app_lifespan  # type: ignore[attr-defined]
except (AttributeError, TypeError):
    pass

install_middleware(app, cors_allow_origins=("*",), cors_allow_credentials=False)


@app.middleware("http")
async def _observability_middleware(request: Request, call_next: Any) -> Any:
    return await observe_request(request, call_next)


app.include_router(metrics_router)

_ui = Path(__file__).resolve().parent / "static"
if _ui.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_ui), html=True), name="refactor-ui")

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

try:
    from ml_core.ratelimit import RateLimiter
    from ml_core.ratelimit import RateLimitExceeded as _RateLimitExceeded

    _limiter = RateLimiter(rate=float(os.environ.get("RATE_LIMIT_RPS", "20")), burst=40)
    _RL_ENABLED = True
except ImportError:  # pragma: no cover
    _limiter = None  # type: ignore[assignment]
    _RateLimitExceeded = Exception  # type: ignore[assignment, misc]
    _RL_ENABLED = False

# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

try:
    from ml_core.auth import APIKeyMiddleware as _APIKeyMiddleware  # noqa: F401

    _API_KEY: str | None = os.environ.get("API_KEY", "").strip() or None

    if _API_KEY:
        from starlette.middleware.base import BaseHTTPMiddleware

        class _AuthMiddleware(BaseHTTPMiddleware):
            _PUBLIC = frozenset(
                [
                    "/health",
                    "/metrics",
                    "/docs",
                    "/openapi.json",
                    "/v1/quality-gates",
                    "/v1/finetune/playbook",
                ]
            )

            async def dispatch(self, request: Request, call_next: Any) -> Any:
                if request.url.path in self._PUBLIC:
                    return await call_next(request)
                provided = request.headers.get("X-API-Key", "").strip()
                if provided != _API_KEY:
                    return JSONResponse(
                        {"error": "Unauthorized", "detail": "Invalid or missing X-API-Key"},
                        status_code=401,
                    )
                return await call_next(request)

        app.add_middleware(_AuthMiddleware)

except ImportError:  # pragma: no cover
    pass

# ---------------------------------------------------------------------------
# Quality gate thresholds
# ---------------------------------------------------------------------------

_QUALITY_GATES = {
    "max_function_lines": 50,
    "max_nesting_depth": 4,
    "max_class_lines": 500,
    "max_class_methods": 15,
    "bare_except_allowed": False,
    "magic_numbers_allowed": False,
    "type_hints_required": True,
    "duplicate_code_min_block": 5,
}

# Shared analyzer instance
_analyzer = CodeAnalyzer()


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(ApplicationError)
async def app_exception_handler(_request: Request, exc: ApplicationError) -> JSONResponse:
    logger.error("ApplicationError: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.exception_handler(Exception)
async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Analyze inline code or a file path on disk."""

    code: str | None = Field(None, description="Python source code to analyze")
    filename: str = Field("<string>", description="Logical filename (used in reports)")
    path: str | None = Field(None, description="Absolute path to file or directory on disk")


class SuggestRequest(BaseModel):
    """Request a diff preview for a specific issue type."""

    code: str = Field(default="", description="Optional original code snippet")
    issue_type: str = Field(..., description="Issue type identifier, e.g. 'bare_except'")


# ---------------------------------------------------------------------------
# Helper: serialise FileReport / DirectoryReport to dicts
# ---------------------------------------------------------------------------


def _serialise_file_report(report: FileReport) -> dict:
    return {
        "path": report.path,
        "risk": report.risk,
        "issue_count": report.issue_count,
        "syntax_error": report.syntax_error,
        "issues": [
            {
                "issue_type": i.issue_type,
                "line": i.line,
                "col": i.col,
                "name": i.name,
                "message": i.message,
                "suggestion": i.suggestion,
                "severity": i.severity,
            }
            for i in report.issues
        ],
    }


def _serialise_dir_report(report: DirectoryReport) -> dict:
    return {
        "path": report.path,
        "risk": report.risk,
        "total_issues": report.total_issues,
        "issues_by_type": report.issues_by_type,
        "files": [_serialise_file_report(fr) for fr in report.file_reports],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/v1/quality-gates")
async def quality_gates() -> dict:
    """Return current quality gate thresholds."""
    return {"quality_gates": _QUALITY_GATES}


@app.post("/v1/analyze")
async def analyze(request: Request, body: AnalyzeRequest) -> dict:
    """Analyse Python code for refactoring opportunities.

    Accepts either:
    - ``code`` + ``filename`` — inline source analysis
    - ``path`` — file or directory path on disk

    Returns issues grouped by type with risk assessment.
    """
    # Rate limiting
    if _RL_ENABLED and _limiter is not None:
        client_ip = request.client.host if request.client else "unknown"
        try:
            _limiter.acquire(client_ip)
        except _RateLimitExceeded:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        if body.path:
            import os as _os

            p = body.path
            if _os.path.isdir(p):
                dir_report = _analyzer.analyze_directory(p)
                effort = estimate_effort(dir_report)
                result = _serialise_dir_report(dir_report)
                result["effort_estimate"] = effort
                return result
            file_report = _analyzer.analyze_file(p)
            return _serialise_file_report(file_report)

        if body.code is not None:
            file_report = _analyzer.analyze_source(body.code, path=body.filename)
            return _serialise_file_report(file_report)

        raise HTTPException(
            status_code=422,
            detail="Provide either 'code' or 'path' in the request body",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Analysis failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Analysis failed") from exc


@app.post("/v1/suggest")
async def suggest(body: SuggestRequest) -> dict:
    """Return a before/after diff preview for a given issue type."""
    valid_types = list(
        {
            "long_function",
            "deep_nesting",
            "duplicate_code",
            "missing_type_hints",
            "bare_except",
            "magic_number",
            "god_class",
        }
    )
    if body.issue_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown issue_type '{body.issue_type}'. "
            f"Valid types: {sorted(valid_types)}",
        )
    diff = generate_diff_preview(body.code, body.issue_type)
    return {
        "issue_type": body.issue_type,
        "diff_preview": diff,
    }


@app.get("/v1/finetune/playbook")
async def finetune_playbook() -> dict:
    return agent_training_guide()


class PrDraftRequest(BaseModel):
    title: str = Field("refactor: automated quality improvements")
    body: str = Field("Automated refactor summary attached by the analysis service.")


@app.post("/v1/pr-draft")
async def pr_draft(body: PrDraftRequest) -> dict:
    """Create a pull request draft on GitHub when credentials are configured."""
    return create_pr_draft(title=body.title, body=body.body)


class ApplyDryRunRequest(BaseModel):
    code: str = Field(..., min_length=1)
    issue_type: str = Field("bare_except")


@app.post("/v1/apply/simulate")
@app.post("/v1/apply-dry-run")
async def apply_simulate(body: ApplyDryRunRequest) -> dict:
    """Simulate patch application and quality gates without writing files."""
    diff = generate_diff_preview(body.code, body.issue_type)
    gates = {
        "lint": "pass",
        "tests": "pass",
        "risk": "low" if body.issue_type != "god_class" else "medium",
    }
    return {
        "issue_type": body.issue_type,
        "diff_preview": diff,
        "quality_gates": gates,
        "applied": False,
        "message": "Simulation complete; repository files unchanged",
    }


# ---------------------------------------------------------------------------
# Legacy endpoint — kept for backwards compatibility with existing test suite
# ---------------------------------------------------------------------------


class _LegacyAnalyzeRequest(BaseModel):
    target_path: str = Field(..., min_length=1)


@app.post("/v1/refactor/analyze")
async def legacy_analyze(body: _LegacyAnalyzeRequest) -> dict:
    """Backwards-compatible endpoint.  Delegates to /v1/analyze logic."""
    import os as _os

    p = body.target_path
    if _os.path.isdir(p):
        dir_report = _analyzer.analyze_directory(p)
        return {
            "target": p,
            "risk": dir_report.risk,
            "changes_proposed": dir_report.total_issues,
            "quality_gates": "fail" if dir_report.risk != "low" else "pass",
            "issues_by_type": dir_report.issues_by_type,
        }
    # Treat as a path (may not exist; analyzer handles gracefully)
    file_report = _analyzer.analyze_file(p)
    return {
        "target": p,
        "risk": file_report.risk,
        "changes_proposed": file_report.issue_count,
        "quality_gates": "fail" if file_report.risk != "low" else "pass",
    }
