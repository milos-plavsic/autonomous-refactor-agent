"""Autonomous code refactoring agent."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from ml_core import configure_logging
from ml_core.exceptions import ApplicationError

logger = configure_logging(__name__)


@dataclass
class RefactoringIssue:
    """A refactoring issue found."""

    type: str
    severity: str  # critical, major, minor
    line: int
    message: str
    suggestion: str


class CodeAnalyzer:
    """Analyze code for refactoring opportunities."""

    @staticmethod
    def analyze_function_length(tree: ast.AST) -> list[RefactoringIssue]:
        """Detect functions that are too long."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 0

                if lines > 50:
                    issues.append(
                        RefactoringIssue(
                            type="long_function",
                            severity="major",
                            line=node.lineno,
                            message=f"Function '{node.name}' is {lines} lines (threshold: 50)",
                            suggestion="Consider breaking into smaller functions",
                        )
                    )

        return issues

    @staticmethod
    def analyze_complexity(tree: ast.AST) -> list[RefactoringIssue]:
        """Detect high cyclomatic complexity."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                complexity = CodeAnalyzer._calculate_complexity(node)

                if complexity > 10:
                    issues.append(
                        RefactoringIssue(
                            type="high_complexity",
                            severity="major",
                            line=node.lineno,
                            message=f"Function '{node.name}' has complexity {complexity}",
                            suggestion="Extract conditions into separate methods",
                        )
                    )

        return issues

    @staticmethod
    def _calculate_complexity(node: ast.AST) -> int:
        """Calculate cyclomatic complexity."""
        complexity = 1

        for child in ast.walk(node):
            if isinstance(child, ast.If | ast.For | ast.While | ast.ExceptHandler):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1

        return complexity

    @staticmethod
    def analyze_naming(tree: ast.AST) -> list[RefactoringIssue]:
        """Detect naming convention violations."""
        issues = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if not re.match(r"^[a-z_][a-z0-9_]*$", node.name):
                    issues.append(
                        RefactoringIssue(
                            type="naming_convention",
                            severity="minor",
                            line=node.lineno,
                            message=f"Function name '{node.name}' violates snake_case",
                            suggestion="Rename to lowercase with underscores",
                        )
                    )

            elif isinstance(node, ast.ClassDef):
                if not re.match(r"^[A-Z][a-zA-Z0-9]*$", node.name):
                    issues.append(
                        RefactoringIssue(
                            type="naming_convention",
                            severity="minor",
                            line=node.lineno,
                            message=f"Class name '{node.name}' violates PascalCase",
                            suggestion="Rename to PascalCase",
                        )
                    )

        return issues

    @staticmethod
    def analyze_unused_imports(tree: ast.AST, source: str) -> list[RefactoringIssue]:
        """Detect unused imports."""
        issues = []

        imports = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.asname or alias.name] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports[alias.asname or alias.name] = node.lineno

        # Check usage
        for name, lineno in imports.items():
            # Skip common modules
            if name.startswith("_"):
                continue

            count = source.count(name)
            if count <= 1:  # Only the import itself
                issues.append(
                    RefactoringIssue(
                        type="unused_import",
                        severity="minor",
                        line=lineno,
                        message=f"Import '{name}' is unused",
                        suggestion="Remove this import",
                    )
                )

        return issues

    @staticmethod
    def analyze_code(source: str) -> list[RefactoringIssue]:
        """Analyze code for refactoring opportunities."""
        issues = []

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ApplicationError(f"Invalid Python syntax: {e}")

        # Run all analyses
        issues.extend(CodeAnalyzer.analyze_function_length(tree))
        issues.extend(CodeAnalyzer.analyze_complexity(tree))
        issues.extend(CodeAnalyzer.analyze_naming(tree))
        issues.extend(CodeAnalyzer.analyze_unused_imports(tree, source))

        return issues


class CodeRefactorer:
    """Refactor code based on issues."""

    @staticmethod
    def apply_fixes(source: str, issues: list[RefactoringIssue]) -> str:
        """Apply refactoring fixes to source code."""
        logger.info(f"Applying {len(issues)} refactoring fixes")

        refactored = source

        # Sort by line number (reverse to avoid offset issues)
        for issue in sorted(issues, key=lambda x: x.line, reverse=True):
            if issue.type == "unused_import":
                refactored = CodeRefactorer._remove_import(refactored, issue.line)

        return refactored

    @staticmethod
    def _remove_import(source: str, line_num: int) -> str:
        """Remove import at specific line."""
        lines = source.split("\n")

        if 0 <= line_num - 1 < len(lines):
            lines.pop(line_num - 1)

        return "\n".join(lines)


async def refactor_code(source: str) -> dict:
    """Refactor code and return issues and suggestions.

    Args:
        source: Python source code

    Returns:
        Dictionary with issues and refactored code
    """
    logger.info("Starting code refactoring analysis")

    try:
        # Analyze
        issues = CodeAnalyzer.analyze_code(source)

        logger.info(f"Found {len(issues)} issues")

        # Group by severity
        by_severity = {}
        for issue in issues:
            if issue.severity not in by_severity:
                by_severity[issue.severity] = []
            by_severity[issue.severity].append(issue)

        logger.info(f"Issues by severity: {dict((k, len(v)) for k, v in by_severity.items())}")

        # Apply fixes
        refactored = CodeRefactorer.apply_fixes(source, issues)

        return {
            "issues": [
                {
                    "type": i.type,
                    "severity": i.severity,
                    "line": i.line,
                    "message": i.message,
                    "suggestion": i.suggestion,
                }
                for i in issues
            ],
            "refactored_code": refactored,
            "total_issues": len(issues),
            "critical": len(by_severity.get("critical", [])),
            "major": len(by_severity.get("major", [])),
            "minor": len(by_severity.get("minor", [])),
        }

    except Exception as e:
        logger.error(f"Refactoring failed: {e}", exc_info=True)
        raise ApplicationError(f"Code refactoring failed: {e}") from e
