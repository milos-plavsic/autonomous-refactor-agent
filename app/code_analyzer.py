"""Python code analysis engine using the standard-library ast module."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CodeIssue:
    """A single detected code quality issue."""

    issue_type: str
    line: int
    col: int
    name: str
    message: str
    suggestion: str
    severity: str  # "low" | "medium" | "high"


@dataclass
class FileReport:
    """All issues found in one source file."""

    path: str
    issues: list[CodeIssue] = field(default_factory=list)
    syntax_error: str | None = None

    @property
    def risk(self) -> str:
        """Aggregate risk level based on issue counts and severities."""
        if self.syntax_error:
            return "high"
        high_count = sum(1 for i in self.issues if i.severity == "high")
        med_count = sum(1 for i in self.issues if i.severity == "medium")
        if high_count >= 2 or (high_count >= 1 and med_count >= 2):
            return "high"
        if high_count >= 1 or med_count >= 3:
            return "medium"
        return "low"

    @property
    def issue_count(self) -> int:
        return len(self.issues)


@dataclass
class DirectoryReport:
    """Aggregated report across all files in a directory."""

    path: str
    file_reports: list[FileReport] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return sum(r.issue_count for r in self.file_reports)

    @property
    def risk(self) -> str:
        """Worst risk across all files."""
        risks = [r.risk for r in self.file_reports]
        if "high" in risks:
            return "high"
        if "medium" in risks:
            return "medium"
        return "low"

    @property
    def issues_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for fr in self.file_reports:
            for issue in fr.issues:
                counts[issue.issue_type] = counts.get(issue.issue_type, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# AST visitors
# ---------------------------------------------------------------------------


class _NestingVisitor(ast.NodeVisitor):
    """Detect maximum nesting depth and flag deep nesting."""

    def __init__(self) -> None:
        self.issues: list[CodeIssue] = []
        self._depth = 0
        self._threshold = 4

    def _enter_block(self, node: ast.AST) -> None:
        self._depth += 1
        if self._depth > self._threshold:
            line = getattr(node, "lineno", 0)
            col = getattr(node, "col_offset", 0)
            self.issues.append(
                CodeIssue(
                    issue_type="deep_nesting",
                    line=line,
                    col=col,
                    name=f"block at line {line}",
                    message=(f"Nesting depth {self._depth} exceeds threshold {self._threshold}"),
                    suggestion=(
                        "Flatten with early returns or guard clauses; extract inner "
                        "logic into a helper function"
                    ),
                    severity="medium",
                )
            )

    def _exit_block(self) -> None:
        self._depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_block(node)
        self.generic_visit(node)
        self._exit_block()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_If(self, node: ast.If) -> None:
        self._enter_block(node)
        self.generic_visit(node)
        self._exit_block()

    def visit_For(self, node: ast.For) -> None:
        self._enter_block(node)
        self.generic_visit(node)
        self._exit_block()

    visit_AsyncFor = visit_For  # type: ignore[assignment]

    def visit_While(self, node: ast.While) -> None:
        self._enter_block(node)
        self.generic_visit(node)
        self._exit_block()

    def visit_With(self, node: ast.With) -> None:
        self._enter_block(node)
        self.generic_visit(node)
        self._exit_block()

    visit_AsyncWith = visit_With  # type: ignore[assignment]

    def visit_Try(self, node: ast.Try) -> None:
        self._enter_block(node)
        self.generic_visit(node)
        self._exit_block()


class _FunctionVisitor(ast.NodeVisitor):
    """Detect long functions and missing type hints."""

    def __init__(self, source_lines: list[str]) -> None:
        self.issues: list[CodeIssue] = []
        self._source_lines = source_lines

    def _check_long_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end = getattr(node, "end_lineno", node.lineno)
        length = end - node.lineno + 1
        if length > 50:
            self.issues.append(
                CodeIssue(
                    issue_type="long_function",
                    line=node.lineno,
                    col=node.col_offset,
                    name=node.name,
                    message=f"Function '{node.name}' is {length} lines (threshold: 50)",
                    suggestion=(
                        f"Extract '{node.name}' into smaller helper functions; "
                        "aim for single-responsibility"
                    ),
                    severity="medium",
                )
            )

    def _check_type_hints(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Skip dunder methods and private helpers
        if node.name.startswith("_"):
            return
        missing: list[str] = []
        for arg in node.args.args:
            if arg.annotation is None:
                missing.append(arg.arg)
        if node.returns is None:
            missing.append("return type")
        if missing:
            self.issues.append(
                CodeIssue(
                    issue_type="missing_type_hints",
                    line=node.lineno,
                    col=node.col_offset,
                    name=node.name,
                    message=(
                        f"Function '{node.name}' missing type annotations for: "
                        + ", ".join(missing)
                    ),
                    suggestion="Add PEP-484 type hints to all parameters and return type",
                    severity="low",
                )
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_long_function(node)
        self._check_type_hints(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_long_function(node)
        self._check_type_hints(node)
        self.generic_visit(node)


class _ExceptionVisitor(ast.NodeVisitor):
    """Detect bare except clauses."""

    def __init__(self) -> None:
        self.issues: list[CodeIssue] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.issues.append(
                CodeIssue(
                    issue_type="bare_except",
                    line=node.lineno,
                    col=node.col_offset,
                    name="except",
                    message="Bare 'except:' clause catches all exceptions including BaseException",
                    suggestion=(
                        "Replace with 'except Exception:' or a specific exception type "
                        "such as 'except (ValueError, KeyError):'"
                    ),
                    severity="high",
                )
            )
        self.generic_visit(node)


class _MagicNumberVisitor(ast.NodeVisitor):
    """Detect magic numeric literals outside of assignments at module level."""

    # Values that are conventionally acceptable as literals
    _ALLOWED = frozenset({0, 1, -1, 2, 100})

    def __init__(self) -> None:
        self.issues: list[CodeIssue] = []
        self._in_assignment = False

    def visit_Assign(self, node: ast.Assign) -> None:
        # Module-level or class-level assignments are usually constants already
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, int | float):
            return
        if isinstance(node.value, bool):
            return
        if node.value in self._ALLOWED:
            return
        self.issues.append(
            CodeIssue(
                issue_type="magic_number",
                line=node.lineno,
                col=node.col_offset,
                name=str(node.value),
                message=f"Magic number {node.value!r} used as a literal",
                suggestion=(
                    f"Extract {node.value!r} into a named constant, "
                    "e.g. MAX_RETRIES = {node.value!r}"
                ),
                severity="low",
            )
        )
        self.generic_visit(node)


class _ClassVisitor(ast.NodeVisitor):
    """Detect God classes (too large, too many methods)."""

    _LINE_THRESHOLD = 500
    _METHOD_THRESHOLD = 15

    def __init__(self) -> None:
        self.issues: list[CodeIssue] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        end = getattr(node, "end_lineno", node.lineno)
        length = end - node.lineno + 1
        methods = [
            n for n in ast.walk(node) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        method_count = len(methods)
        if length > self._LINE_THRESHOLD or method_count > self._METHOD_THRESHOLD:
            reasons = []
            if length > self._LINE_THRESHOLD:
                reasons.append(f"{length} lines (threshold {self._LINE_THRESHOLD})")
            if method_count > self._METHOD_THRESHOLD:
                reasons.append(f"{method_count} methods (threshold {self._METHOD_THRESHOLD})")
            self.issues.append(
                CodeIssue(
                    issue_type="god_class",
                    line=node.lineno,
                    col=node.col_offset,
                    name=node.name,
                    message=f"God class '{node.name}': " + ", ".join(reasons),
                    suggestion=(
                        f"Decompose '{node.name}' by extracting cohesive sub-classes "
                        "or standalone functions"
                    ),
                    severity="high",
                )
            )
        self.generic_visit(node)


def _detect_duplicates(source: str) -> list[CodeIssue]:
    """Detect duplicate code blocks (>=5 identical non-blank lines in sequence)."""
    issues: list[CodeIssue] = []
    lines = source.splitlines()
    # Strip and filter blank/comment lines for comparison
    stripped = [
        (i + 1, ln.strip())
        for i, ln in enumerate(lines)
        if ln.strip() and not ln.strip().startswith("#")
    ]

    window = 5
    seen: dict[tuple[str, ...], int] = {}
    for i in range(len(stripped) - window + 1):
        chunk = tuple(sl for _, sl in stripped[i : i + window])
        first_line = stripped[i][0]
        if chunk in seen:
            issues.append(
                CodeIssue(
                    issue_type="duplicate_code",
                    line=first_line,
                    col=0,
                    name=f"lines {first_line}-{first_line + window - 1}",
                    message=(
                        f"Duplicate code block ({window} lines) starting at line {first_line}, "
                        f"previously seen near line {seen[chunk]}"
                    ),
                    suggestion=(
                        "Extract the duplicated logic into a shared helper function "
                        "to follow the DRY principle"
                    ),
                    severity="medium",
                )
            )
        else:
            seen[chunk] = first_line
    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class CodeAnalyzer:
    """Analyse Python source files for refactoring opportunities."""

    def analyze_source(self, source: str, path: str = "<string>") -> FileReport:
        """Parse and analyse *source* string.  Returns a :class:`FileReport`."""
        report = FileReport(path=path)
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            report.syntax_error = str(exc)
            return report

        source_lines = source.splitlines()

        # Run all visitors
        nesting = _NestingVisitor()
        nesting.visit(tree)
        report.issues.extend(nesting.issues)

        funcs = _FunctionVisitor(source_lines)
        funcs.visit(tree)
        report.issues.extend(funcs.issues)

        excepts = _ExceptionVisitor()
        excepts.visit(tree)
        report.issues.extend(excepts.issues)

        magic = _MagicNumberVisitor()
        magic.visit(tree)
        report.issues.extend(magic.issues)

        classes = _ClassVisitor()
        classes.visit(tree)
        report.issues.extend(classes.issues)

        report.issues.extend(_detect_duplicates(source))

        # De-duplicate issues at the exact same (type, line)
        seen: set[tuple[str, int]] = set()
        deduped: list[CodeIssue] = []
        for issue in report.issues:
            key = (issue.issue_type, issue.line)
            if key not in seen:
                seen.add(key)
                deduped.append(issue)
        report.issues = sorted(deduped, key=lambda i: i.line)
        return report

    def analyze_file(self, path: str) -> FileReport:
        """Read a file from disk and analyse it."""
        p = Path(path)
        if not p.exists():
            report = FileReport(path=path)
            report.syntax_error = f"File not found: {path}"
            return report
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report = FileReport(path=path)
            report.syntax_error = str(exc)
            return report
        return self.analyze_source(source, path=path)

    def analyze_directory(self, dir_path: str) -> DirectoryReport:
        """Recursively analyse all ``*.py`` files under *dir_path*."""
        root = Path(dir_path)
        report = DirectoryReport(path=dir_path)
        if not root.exists() or not root.is_dir():
            return report
        for py_file in sorted(root.rglob("*.py")):
            if any(part.startswith(".") for part in py_file.parts):
                continue  # skip hidden directories
            report.file_reports.append(self.analyze_file(str(py_file)))
        return report
