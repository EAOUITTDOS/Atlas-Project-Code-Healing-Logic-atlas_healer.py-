"""Conservative, offline repair tools for reproducible Python research scripts.

The healer never runs scanned code or shell commands. It writes repairs to a
separate output file and reports issues it cannot safely fix automatically.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import tempfile
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


SHELL_ESCAPE_RE = re.compile(r"^(?P<indent>\s*)(?P<escape>!|%)(?P<body>.*)$")


@dataclass(frozen=True)
class Finding:
    """One reproducibility or syntax issue found in a source file."""

    code: str
    line: int
    message: str
    suggestion: str


@dataclass
class ScanReport:
    path: str
    findings: list[Finding]
    syntax_valid: bool

    @property
    def reproducible(self) -> bool:
        return self.syntax_valid and not self.findings


class AtlasHealer:
    """Scan Python research scripts and produce conservative repaired copies."""

    def __init__(self, file_path: str | os.PathLike[str]):
        self.file_path = Path(file_path)
        if not self.file_path.is_file():
            raise FileNotFoundError(f"Critical failure: {self.file_path} not found")

    def _read_source(self) -> str:
        try:
            return self.file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{self.file_path} is not valid UTF-8 text") from exc

    @staticmethod
    def _absolute_string_literals(source: str) -> Iterable[tuple[int, str]]:
        """Yield absolute filesystem paths expressed as Python string constants."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if value.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
                    yield node.lineno, value

    @staticmethod
    def _shell_escape_lines(source: str) -> set[int]:
        """Find notebook-style !/% commands, excluding occurrences in strings/comments."""
        protected: dict[int, list[tuple[int, int]]] = {}
        try:
            for token in tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__):
                if token.type in (tokenize.STRING, tokenize.COMMENT):
                    start_line, start_col = token.start
                    end_line, end_col = token.end
                    for line_no in range(start_line, end_line + 1):
                        left = start_col if line_no == start_line else 0
                        right = end_col if line_no == end_line else 10**9
                        protected.setdefault(line_no, []).append((left, right))
        except (tokenize.TokenError, IndentationError, StopIteration):
            # Incomplete notebook syntax can stop tokenization; the line-prefix
            # check below remains conservative and only considers leading ! or %.
            pass

        found: set[int] = set()
        for line_no, line in enumerate(source.splitlines(), start=1):
            match = SHELL_ESCAPE_RE.match(line)
            if not match:
                continue
            col = len(match.group("indent"))
            if not any(left <= col < right for left, right in protected.get(line_no, [])):
                found.add(line_no)
        return found

    def scan_reproducibility(self) -> ScanReport:
        source = self._read_source()
        findings: list[Finding] = []
        shell_lines = self._shell_escape_lines(source)
        for line_no in sorted(shell_lines):
            findings.append(Finding(
                code="IPYTHON_SHELL_ESCAPE",
                line=line_no,
                message="Notebook shell/magic command is not standard Python and will not be run.",
                suggestion="Move setup commands to documented environment instructions, or keep them commented as provenance.",
            ))

        for line_no, value in self._absolute_string_literals(source):
            findings.append(Finding(
                code="ABSOLUTE_PATH",
                line=line_no,
                message=f"Absolute path is machine-specific: {value!r}.",
                suggestion="Use a project-relative path or a configurable CLI/environment setting; verify the data file exists.",
            ))

        # Shell escapes are diagnosed separately; remove only those lines from
        # the parse input to reveal additional Python syntax errors accurately.
        parse_lines = source.splitlines(keepends=True)
        for line_no in shell_lines:
            parse_lines[line_no - 1] = "\n" if parse_lines[line_no - 1].endswith("\n") else ""
        try:
            ast.parse("".join(parse_lines), filename=str(self.file_path))
            syntax_valid = True
        except SyntaxError as exc:
            syntax_valid = False
            findings.append(Finding(
                code="PYTHON_SYNTAX_ERROR",
                line=exc.lineno or 1,
                message=exc.msg,
                suggestion="Review and correct this syntax manually; the healer will not guess at intended program logic.",
            ))

        findings.sort(key=lambda item: (item.line, item.code))
        return ScanReport(str(self.file_path), findings, syntax_valid)

    @staticmethod
    def _neutralize_shell_escapes(source: str) -> tuple[str, int]:
        lines = source.splitlines(keepends=True)
        shell_lines = AtlasHealer._shell_escape_lines(source)
        for line_no in shell_lines:
            line = lines[line_no - 1]
            ending = "\n" if line.endswith("\n") else ""
            content = line[:-1] if ending else line
            indent = len(content) - len(content.lstrip())
            lines[line_no - 1] = content[:indent] + "# ATLAS-HEALED (not executed): " + content[indent:] + ending
        return "".join(lines), len(shell_lines)

    def heal(self, output_path: str | os.PathLike[str] | None = None) -> tuple[Path, ScanReport, int]:
        """Write a copy with notebook shell lines safely commented out.

        Absolute paths and Python syntax errors are reported but not rewritten:
        guessing a data-file location or intended syntax could corrupt research.
        """
        source = self._read_source()
        repaired, edits = self._neutralize_shell_escapes(source)
        destination = Path(output_path) if output_path else self.file_path.with_name(
            f"{self.file_path.stem}_healed{self.file_path.suffix}"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement prevents a partial output if a write is interrupted.
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", newline="", dir=destination.parent,
                prefix=f".{destination.name}.", suffix=".tmp", delete=False,
            ) as temp:
                temp.write(repaired)
                temp_name = temp.name
            os.replace(temp_name, destination)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

        report = AtlasHealer(destination).scan_reproducibility()
        return destination, report, edits


# Backwards-compatible name used in the original terminal proof of concept.
JesseJamesLogic = AtlasHealer


def _print_report(report: ScanReport) -> None:
    print(f"[SCAN] {report.path}")
    if report.reproducible:
        print("[OK] Python syntax is valid; no reproducibility findings.")
        return
    for finding in report.findings:
        print(f"[{finding.code}] line {finding.line}: {finding.message}")
        print(f"  suggestion: {finding.suggestion}")
    if not report.syntax_valid:
        print("[REVIEW] Output still contains syntax errors; it was not declared healed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Conservative offline Atlas code scanner/healer")
    parser.add_argument("file", help="Python file to inspect (never executed)")
    parser.add_argument("--heal", action="store_true", help="Write a separate copy with notebook shell escapes commented out")
    parser.add_argument("--output", help="Output path for --heal (default: <name>_healed.py)")
    parser.add_argument("--json", action="store_true", help="Print findings as JSON")
    args = parser.parse_args(argv)

    try:
        healer = AtlasHealer(args.file)
        if args.heal:
            output, report, edits = healer.heal(args.output)
            print(f"[HEAL] Wrote {output} (commented out {edits} notebook shell/magic line(s)).")
        else:
            report = healer.scan_reproducibility()
        if args.json:
            print(json.dumps({
                "path": report.path,
                "syntax_valid": report.syntax_valid,
                "reproducible": report.reproducible,
                "findings": [asdict(item) for item in report.findings],
            }, indent=2))
        else:
            _print_report(report)
        return 0 if report.reproducible else 1
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
