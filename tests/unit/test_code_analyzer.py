"""Unit tests for CodeAnalyzer, FileReport, DirectoryReport, and refactor_suggestions."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.code_analyzer import (
    CodeAnalyzer,
    CodeIssue,
    DirectoryReport,
    FileReport,
    _detect_duplicates,
)
from app.refactor_suggestions import estimate_effort, generate_diff_preview

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer() -> CodeAnalyzer:
    return CodeAnalyzer()


# ---------------------------------------------------------------------------
# analyze_source — bare except detection
# ---------------------------------------------------------------------------


def test_bare_except_detected(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def fetch():
            try:
                return call()
            except:
                pass
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "bare_except" in types


def test_bare_except_severity_is_high(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        try:
            x = 1
        except:
            pass
    """)
    report = analyzer.analyze_source(source)
    high_issues = [i for i in report.issues if i.issue_type == "bare_except"]
    assert all(i.severity == "high" for i in high_issues)


def test_specific_except_not_flagged(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        try:
            x = int("abc")
        except ValueError:
            pass
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "bare_except" not in types


# ---------------------------------------------------------------------------
# analyze_source — missing type hints
# ---------------------------------------------------------------------------


def test_missing_type_hints_detected(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def add(a, b):
            return a + b
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "missing_type_hints" in types


def test_fully_annotated_function_not_flagged(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def add(a: int, b: int) -> int:
            return a + b
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "missing_type_hints" not in types


def test_private_function_skips_type_hint_check(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def _helper(x, y):
            return x + y
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "missing_type_hints" not in types


# ---------------------------------------------------------------------------
# analyze_source — long function detection
# ---------------------------------------------------------------------------


def test_long_function_detected(analyzer: CodeAnalyzer) -> None:
    # Build a function with 55 lines
    body_lines = "\n".join(f"    x_{i} = {i}" for i in range(53))
    source = f"def big_func():\n{body_lines}\n    return x_0\n"
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "long_function" in types


def test_short_function_not_flagged(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def small(a: int) -> int:
            return a + 1
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "long_function" not in types


# ---------------------------------------------------------------------------
# analyze_source — deep nesting detection
# ---------------------------------------------------------------------------


def test_deep_nesting_detected(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def deep():
            if True:
                for x in range(10):
                    while True:
                        if x:
                            with open("f") as f:
                                pass
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "deep_nesting" in types


def test_shallow_nesting_not_flagged(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def shallow():
            if True:
                return 1
            return 0
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "deep_nesting" not in types


# ---------------------------------------------------------------------------
# analyze_source — magic number detection
# ---------------------------------------------------------------------------


def test_magic_number_detected(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def retry():
            for i in range(7):
                pass
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "magic_number" in types


def test_allowed_literal_not_flagged(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def zero():
            return 0
    """)
    report = analyzer.analyze_source(source)
    types = [i.issue_type for i in report.issues]
    assert "magic_number" not in types


# ---------------------------------------------------------------------------
# analyze_source — syntax error handling
# ---------------------------------------------------------------------------


def test_syntax_error_captured(analyzer: CodeAnalyzer) -> None:
    report = analyzer.analyze_source("def broken(:\n    pass")
    assert report.syntax_error is not None
    assert len(report.issues) == 0


def test_syntax_error_sets_risk_to_high(analyzer: CodeAnalyzer) -> None:
    report = analyzer.analyze_source("class Bad(:")
    assert report.risk == "high"


# ---------------------------------------------------------------------------
# FileReport risk levels
# ---------------------------------------------------------------------------


def test_file_report_risk_low_no_issues() -> None:
    report = FileReport(path="test.py")
    assert report.risk == "low"


def test_file_report_risk_high_with_two_high_severity_issues() -> None:
    report = FileReport(path="test.py")
    for _ in range(2):
        report.issues.append(
            CodeIssue(
                issue_type="bare_except",
                line=1,
                col=0,
                name="except",
                message="bare except",
                suggestion="fix it",
                severity="high",
            )
        )
    assert report.risk == "high"


def test_file_report_issue_count() -> None:
    report = FileReport(path="test.py")
    report.issues.append(CodeIssue("bare_except", 1, 0, "e", "msg", "sug", "high"))
    assert report.issue_count == 1


# ---------------------------------------------------------------------------
# DirectoryReport aggregation
# ---------------------------------------------------------------------------


def test_directory_report_total_issues() -> None:
    dir_report = DirectoryReport(path="/tmp")
    fr1 = FileReport(path="a.py")
    fr1.issues.append(CodeIssue("bare_except", 1, 0, "e", "msg", "sug", "high"))
    fr2 = FileReport(path="b.py")
    fr2.issues.append(CodeIssue("magic_number", 2, 0, "5", "msg", "sug", "low"))
    dir_report.file_reports = [fr1, fr2]
    assert dir_report.total_issues == 2


def test_directory_report_risk_worst_wins() -> None:
    dir_report = DirectoryReport(path="/tmp")
    low_report = FileReport(path="clean.py")
    high_report = FileReport(path="messy.py")
    high_report.issues.append(CodeIssue("bare_except", 1, 0, "e", "msg", "sug", "high"))
    high_report.issues.append(CodeIssue("bare_except", 2, 0, "e", "msg", "sug", "high"))
    dir_report.file_reports = [low_report, high_report]
    assert dir_report.risk == "high"


def test_directory_report_issues_by_type() -> None:
    dir_report = DirectoryReport(path="/tmp")
    fr = FileReport(path="a.py")
    fr.issues.append(CodeIssue("bare_except", 1, 0, "e", "msg", "sug", "high"))
    fr.issues.append(CodeIssue("bare_except", 5, 0, "e", "msg", "sug", "high"))
    fr.issues.append(CodeIssue("magic_number", 3, 0, "7", "msg", "sug", "low"))
    dir_report.file_reports = [fr]
    by_type = dir_report.issues_by_type
    assert by_type["bare_except"] == 2
    assert by_type["magic_number"] == 1


# ---------------------------------------------------------------------------
# _detect_duplicates
# ---------------------------------------------------------------------------


def test_duplicate_code_detected() -> None:
    block = "\n".join([f"    x_{i} = {i}" for i in range(5)])
    # Repeat the same block twice in different functions
    source = f"def func_a():\n{block}\n\ndef func_b():\n{block}\n"
    issues = _detect_duplicates(source)
    types = [i.issue_type for i in issues]
    assert "duplicate_code" in types


def test_no_duplicate_for_unique_code() -> None:
    source = textwrap.dedent("""\
        def a():
            x = 1
            y = 2

        def b():
            z = 3
            w = 4
    """)
    issues = _detect_duplicates(source)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# analyze_file — file not found
# ---------------------------------------------------------------------------


def test_analyze_file_not_found(analyzer: CodeAnalyzer) -> None:
    report = analyzer.analyze_file("/nonexistent/path/file.py")
    assert report.syntax_error is not None
    assert "not found" in report.syntax_error.lower() or "no such" in report.syntax_error.lower()


# ---------------------------------------------------------------------------
# analyze_directory — returns empty for nonexistent dir
# ---------------------------------------------------------------------------


def test_analyze_directory_nonexistent(analyzer: CodeAnalyzer) -> None:
    report = analyzer.analyze_directory("/nonexistent/dir")
    assert report.total_issues == 0
    assert len(report.file_reports) == 0


def test_analyze_directory_scans_py_files(analyzer: CodeAnalyzer, tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "bad.py").write_text("try:\n    pass\nexcept:\n    pass\n")
    report = analyzer.analyze_directory(str(tmp_path))
    assert len(report.file_reports) == 2
    all_types = {i.issue_type for fr in report.file_reports for i in fr.issues}
    assert "bare_except" in all_types


# ---------------------------------------------------------------------------
# refactor_suggestions — generate_diff_preview
# ---------------------------------------------------------------------------


def test_generate_diff_preview_bare_except() -> None:
    diff = generate_diff_preview("", "bare_except")
    assert "# BEFORE" in diff
    assert "# AFTER" in diff
    assert "except" in diff.lower()


def test_generate_diff_preview_uses_provided_code() -> None:
    original = "try:\n    pass\nexcept:\n    pass"
    diff = generate_diff_preview(original, "bare_except")
    assert original in diff


def test_generate_diff_preview_all_issue_types() -> None:
    issue_types = [
        "long_function",
        "deep_nesting",
        "duplicate_code",
        "missing_type_hints",
        "bare_except",
        "magic_number",
        "god_class",
    ]
    for itype in issue_types:
        diff = generate_diff_preview("", itype)
        assert "# BEFORE" in diff, f"Missing BEFORE section for {itype}"
        assert "# AFTER" in diff, f"Missing AFTER section for {itype}"


# ---------------------------------------------------------------------------
# refactor_suggestions — estimate_effort
# ---------------------------------------------------------------------------


def test_estimate_effort_returns_expected_keys() -> None:
    dir_report = DirectoryReport(path="/tmp")
    result = estimate_effort(dir_report)
    assert "total_minutes" in result
    assert "total_hours" in result
    assert "complexity" in result
    assert "by_issue_type" in result
    assert "file_count" in result


def test_estimate_effort_zero_for_clean_repo() -> None:
    dir_report = DirectoryReport(path="/tmp")
    dir_report.file_reports = [FileReport(path="clean.py")]
    result = estimate_effort(dir_report)
    assert result["total_minutes"] == 0
    assert result["complexity"] == "low"
    assert result["file_count"] == 0


def test_estimate_effort_bare_except_costs_10_minutes() -> None:
    dir_report = DirectoryReport(path="/tmp")
    fr = FileReport(path="a.py")
    fr.issues.append(CodeIssue("bare_except", 1, 0, "e", "msg", "sug", "high"))
    dir_report.file_reports = [fr]
    result = estimate_effort(dir_report)
    assert result["total_minutes"] == 10
    assert result["by_issue_type"]["bare_except"] == 10


def test_estimate_effort_complexity_high_above_threshold() -> None:
    dir_report = DirectoryReport(path="/tmp")
    fr = FileReport(path="a.py")
    # god_class = 120 min each; need >= 481 for "high"
    for i in range(5):
        fr.issues.append(CodeIssue("god_class", i * 100 + 1, 0, f"C{i}", "msg", "sug", "high"))
    dir_report.file_reports = [fr]
    result = estimate_effort(dir_report)
    assert result["complexity"] == "high"


# ---------------------------------------------------------------------------
# Issue ordering (results sorted by line number)
# ---------------------------------------------------------------------------


def test_issues_sorted_by_line(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        def public_func(x, y):
            return x + y

        try:
            pass
        except:
            pass
    """)
    report = analyzer.analyze_source(source)
    lines = [i.line for i in report.issues]
    assert lines == sorted(lines)


# ---------------------------------------------------------------------------
# De-duplication of issues at same (type, line)
# ---------------------------------------------------------------------------


def test_no_duplicate_issues_at_same_line(analyzer: CodeAnalyzer) -> None:
    source = textwrap.dedent("""\
        try:
            pass
        except:
            pass
    """)
    report = analyzer.analyze_source(source)
    seen: set[tuple[str, int]] = set()
    for issue in report.issues:
        key = (issue.issue_type, issue.line)
        assert key not in seen, f"Duplicate issue at {key}"
        seen.add(key)
