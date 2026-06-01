"""Refactoring diff previews and effort estimation."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.code_analyzer import DirectoryReport

# ---------------------------------------------------------------------------
# Diff preview templates
# ---------------------------------------------------------------------------

_BEFORE_LABEL = "# BEFORE"
_AFTER_LABEL = "# AFTER (suggested)"

_TEMPLATES: dict[str, tuple[str, str]] = {
    "long_function": (
        textwrap.dedent("""\
            def process_all_data(records):
                result = []
                for record in records:
                    # ... 60 more lines of logic ...
                    validated = validate(record)
                    transformed = transform(validated)
                    result.append(transformed)
                return result
        """),
        textwrap.dedent("""\
            def _validate_record(record):
                \"\"\"Single responsibility: validate one record.\"\"\"
                return validate(record)

            def _transform_record(record):
                \"\"\"Single responsibility: transform one record.\"\"\"
                return transform(record)

            def process_all_data(records):
                \"\"\"Orchestrate validation and transformation.\"\"\"
                return [_transform_record(_validate_record(r)) for r in records]
        """),
    ),
    "deep_nesting": (
        textwrap.dedent("""\
            def handle_request(request):
                if request:
                    if request.user:
                        if request.user.is_active:
                            if request.data:
                                return process(request.data)
        """),
        textwrap.dedent("""\
            def handle_request(request):
                if not request:
                    return None
                if not request.user:
                    return None
                if not request.user.is_active:
                    return None
                if not request.data:
                    return None
                return process(request.data)
        """),
    ),
    "duplicate_code": (
        textwrap.dedent("""\
            def process_orders(orders):
                for o in orders:
                    total = o.price * o.qty
                    tax = total * 0.2
                    final = total + tax
                    print(final)

            def process_returns(returns):
                for r in returns:
                    total = r.price * r.qty
                    tax = total * 0.2
                    final = total + tax
                    print(final)
        """),
        textwrap.dedent("""\
            def _calculate_total_with_tax(price: float, qty: int, tax_rate: float = 0.2) -> float:
                \"\"\"DRY: single source of truth for total calculation.\"\"\"
                total = price * qty
                return total + total * tax_rate

            def process_orders(orders):
                for o in orders:
                    print(_calculate_total_with_tax(o.price, o.qty))

            def process_returns(returns):
                for r in returns:
                    print(_calculate_total_with_tax(r.price, r.qty))
        """),
    ),
    "missing_type_hints": (
        textwrap.dedent("""\
            def add(a, b):
                return a + b

            def greet(name):
                return f"Hello, {name}"
        """),
        textwrap.dedent("""\
            def add(a: float, b: float) -> float:
                return a + b

            def greet(name: str) -> str:
                return f"Hello, {name}"
        """),
    ),
    "bare_except": (
        textwrap.dedent("""\
            try:
                result = fetch_data()
            except:
                pass
        """),
        textwrap.dedent("""\
            try:
                result = fetch_data()
            except (ConnectionError, TimeoutError) as exc:
                logger.warning("fetch_data failed: %s", exc)
                result = None
        """),
    ),
    "magic_number": (
        textwrap.dedent("""\
            def retry(func):
                for attempt in range(3):
                    if func():
                        return True
                    time.sleep(0.5)
                return False
        """),
        textwrap.dedent("""\
            MAX_RETRIES = 3
            RETRY_DELAY_SECONDS = 0.5

            def retry(func):
                for attempt in range(MAX_RETRIES):
                    if func():
                        return True
                    time.sleep(RETRY_DELAY_SECONDS)
                return False
        """),
    ),
    "god_class": (
        textwrap.dedent("""\
            class Application:
                # 600+ lines, 20+ methods handling HTTP, DB, caching, auth, email...
                def handle_request(self): ...
                def connect_db(self): ...
                def cache_result(self): ...
                def send_email(self): ...
                # ... 16 more methods
        """),
        textwrap.dedent("""\
            class HttpHandler:
                def handle_request(self): ...

            class DatabaseClient:
                def connect(self): ...

            class CacheClient:
                def cache_result(self): ...

            class EmailService:
                def send_email(self): ...

            class Application:
                \"\"\"Thin orchestrator; each concern lives in its own class.\"\"\"
                def __init__(self):
                    self.http = HttpHandler()
                    self.db = DatabaseClient()
                    self.cache = CacheClient()
                    self.email = EmailService()
        """),
    ),
}

# ---------------------------------------------------------------------------
# Effort estimation
# ---------------------------------------------------------------------------

# Minutes of effort per issue instance, by issue type
_EFFORT_MINUTES: dict[str, int] = {
    "long_function": 60,  # extraction + tests
    "deep_nesting": 30,  # guard clauses
    "duplicate_code": 45,  # DRY + tests
    "missing_type_hints": 5,  # annotation only
    "bare_except": 10,  # specific exception
    "magic_number": 5,  # named constant
    "god_class": 120,  # decomposition
}

_COMPLEXITY_THRESHOLDS = {
    "low": 120,  # < 2 hours total
    "medium": 480,  # < 8 hours total
}


def generate_diff_preview(original: str, issue_type: str) -> str:
    """Return a before/after diff snippet for *issue_type*.

    If *original* is provided and non-empty it is shown as the BEFORE block;
    otherwise the canned template is used.
    """
    before_template, after_template = _TEMPLATES.get(
        issue_type, ("# No template available for this issue type", "")
    )
    before = original.strip() if original.strip() else before_template.strip()

    lines = [
        f"{_BEFORE_LABEL}",
        before,
        "",
        f"{_AFTER_LABEL}",
        after_template.strip(),
    ]
    return "\n".join(lines)


def estimate_effort(report: DirectoryReport) -> dict:
    """Estimate refactoring effort for all issues in *report*.

    Returns a dict with:
      - ``total_minutes``: sum of all effort estimates
      - ``complexity``: "low" | "medium" | "high"
      - ``by_issue_type``: per-type breakdown
      - ``file_count``: number of files with issues
    """
    by_type: dict[str, int] = {}
    total_minutes = 0
    files_with_issues = 0

    for file_report in report.file_reports:
        if file_report.issue_count == 0:
            continue
        files_with_issues += 1
        for issue in file_report.issues:
            minutes = _EFFORT_MINUTES.get(issue.issue_type, 15)
            by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + minutes
            total_minutes += minutes

    if total_minutes < _COMPLEXITY_THRESHOLDS["low"]:
        complexity = "low"
    elif total_minutes < _COMPLEXITY_THRESHOLDS["medium"]:
        complexity = "medium"
    else:
        complexity = "high"

    return {
        "total_minutes": total_minutes,
        "total_hours": round(total_minutes / 60, 1),
        "complexity": complexity,
        "by_issue_type": by_type,
        "file_count": files_with_issues,
    }
