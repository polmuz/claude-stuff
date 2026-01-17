#!/usr/bin/env python3
"""
Claude Code Session Transcript Analyzer

Analyzes Claude Code session JSONL files to identify patterns of errors,
failed commands, and issues that the AI agent encountered.

Usage:
    python analyze_sessions.py [--cwd PATH] [--top N] [--output FORMAT]

Arguments:
    --cwd PATH      Working directory to detect project sessions from
                    Default: current directory
    --top N         Analyze top N largest session files (default: 25)
    --output FORMAT Output format: 'text' or 'json' (default: json)
    --exclude       Comma-separated session IDs to exclude
"""

import os
import sys
import json
import re
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def cwd_to_session_dir(cwd: str) -> str | None:
    """Convert a working directory path to the Claude sessions directory path.

    Returns the path if found, None otherwise.
    """
    projects_dir = Path(os.path.expanduser('~/.claude/projects'))
    if not projects_dir.exists():
        return None

    # Try the resolved path first
    path = Path(cwd).resolve()
    path_str = path.as_posix().replace('/', '-')
    if not path_str.startswith('-'):
        path_str = '-' + path_str

    candidate = projects_dir / path_str
    if candidate.exists():
        return str(candidate) + '/'

    # Try with the original path (not resolved, in case of symlinks)
    path_str_orig = Path(cwd).as_posix().replace('/', '-')
    if not path_str_orig.startswith('-'):
        path_str_orig = '-' + path_str_orig

    candidate_orig = projects_dir / path_str_orig
    if candidate_orig.exists():
        return str(candidate_orig) + '/'

    # Fallback: search for directories ending with the project name
    project_name = Path(cwd).name
    for d in projects_dir.iterdir():
        if d.is_dir() and d.name.endswith('-' + project_name):
            return str(d) + '/'

    return None


def find_all_session_dirs() -> list[str]:
    """Find all session directories in ~/.claude/projects/."""
    projects_dir = Path(os.path.expanduser('~/.claude/projects'))
    if not projects_dir.exists():
        return []
    return [str(d) + '/' for d in projects_dir.iterdir() if d.is_dir()]


def extract_text_recursive(obj: Any) -> list[str]:
    """Recursively extract all text strings from a JSON object."""
    texts = []
    if isinstance(obj, dict):
        for v in obj.values():
            texts.extend(extract_text_recursive(v))
    elif isinstance(obj, list):
        for item in obj:
            texts.extend(extract_text_recursive(item))
    elif isinstance(obj, str):
        texts.append(obj)
    return texts


def find_text_with_context(obj: Any, patterns: list[str], context_before: int = 30, context_after: int = 150) -> list[str]:
    """Find text matching patterns and return with surrounding context."""
    results = []

    def search(o):
        if isinstance(o, str):
            for pattern in patterns:
                if pattern.lower() in o.lower():
                    idx = o.lower().find(pattern.lower())
                    start = max(0, idx - context_before)
                    end = min(len(o), idx + context_after)
                    results.append(o[start:end])
        elif isinstance(o, dict):
            for v in o.values():
                search(v)
        elif isinstance(o, list):
            for item in o:
                search(item)

    search(obj)
    return results


def is_meta_content(text: str) -> bool:
    """Check if text is meta-content (shell commands, analysis output, etc.)."""
    meta_indicators = [
        # Shell commands
        'grep ', 'awk ', 'sed ', 'cat ', 'wc -l', 'sort |', 'uniq -c',
        '#!/', 'python3 -c', 'python3 <<', 'PYEOF', 'bash -c',
        '.jsonl:', '.jsonl |', '2>/dev/null', '/dev/null',
        '| head', '| tail', '| grep',
        # Analysis output
        'occurrences) ###', '## Recommended', '## Reduce',
        'CLAUDE CODE SESSION', 'ANALYSIS REPORT',
        'fix_categories', 'retry_patterns', 'build_failures',
        # JSON-like output
        '"count":', '"examples":', 'Total:',
        # Session paths
        '/.claude/projects/',
        # Code patterns that aren't actual fixes
        "'let me fix'", '"let me fix"',
        "'i need to fix'", '"i need to fix"',
        "'try again'", '"try again"',
        # Regex patterns
        're.findall', 're.IGNORECASE', 'r\'.{', 'r".{',
        'full_text,', 'full_content,',
    ]
    text_lower = text.lower()
    return any(indicator.lower() in text_lower for indicator in meta_indicators)


def deduplicate_contexts(contexts: list[str], similarity_threshold: int = 50) -> list[str]:
    """Remove near-duplicate contexts based on prefix similarity."""
    if not contexts:
        return []

    seen_prefixes = set()
    unique = []

    for ctx in contexts:
        # Use first N chars as a fingerprint for deduplication
        prefix = ctx[:similarity_threshold].lower()
        if prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            unique.append(ctx)

    return unique


class SessionAnalyzer:
    """Analyzes Claude Code session transcripts for error patterns."""

    # Fix patterns to search for
    FIX_PATTERNS = ['I need to fix', 'let me fix', 'Now I need to fix']

    # Apology patterns
    APOLOGY_PATTERNS = ['apologize', 'sorry', 'my mistake', 'I should have']

    # Sessions with more than this many build failures per message are likely
    # containing analysis output and should be flagged
    BUILD_FAILURE_OUTLIER_THRESHOLD = 1000

    def __init__(self, session_dir: str, exclude_sessions: list[str] = None):
        self.session_dir = Path(session_dir)
        self.exclude_sessions = exclude_sessions or []

        # Aggregated results
        self.build_failures = defaultdict(int)
        self.fix_contexts = []
        self.apology_contexts = []
        self.retry_patterns = Counter()
        self.sessions_analyzed = 0
        self.outlier_sessions = []  # Sessions with suspicious high counts

    def get_session_files(self, top_n: int = 25) -> list[tuple[str, int]]:
        """Get session files sorted by size, excluding agent files."""
        if not self.session_dir.exists():
            return []

        files = []
        for f in self.session_dir.iterdir():
            if not f.name.endswith('.jsonl'):
                continue
            if f.name.startswith('agent-'):
                continue
            if any(exc in f.name for exc in self.exclude_sessions):
                continue
            files.append((f.name, f.stat().st_size))

        files.sort(key=lambda x: -x[1])
        return files[:top_n]

    def analyze_session(self, filename: str):
        """Analyze a single session file."""
        filepath = self.session_dir / filename
        session_name = filename[:30]

        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        self._analyze_message(obj, session_name)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"Error processing {filename}: {e}", file=sys.stderr)

    def _analyze_message(self, obj: dict, session_name: str):
        """Analyze a single message object."""
        texts = extract_text_recursive(obj)
        full_text = '\n'.join(texts)

        # Build failures (generic - works for many build systems)
        build_fail_count = full_text.count('BUILD FAILED')
        if build_fail_count > 0:
            self.build_failures[session_name] += build_fail_count

        # Fix contexts (filter out meta-content)
        fix_results = find_text_with_context(obj, self.FIX_PATTERNS)
        for result in fix_results:
            result = result.replace('\\n', ' ').replace('\n', ' ')
            result = re.sub(r'\s+', ' ', result).strip()
            if len(result) > 30 and not is_meta_content(result):
                self.fix_contexts.append(result[:180])

        # Apology contexts (filter out meta-content)
        apology_results = find_text_with_context(obj, self.APOLOGY_PATTERNS)
        for result in apology_results:
            result = result.replace('\\n', ' ').replace('\n', ' ')
            result = re.sub(r'\s+', ' ', result).strip()
            if len(result) > 30 and not is_meta_content(result):
                self.apology_contexts.append(result[:180])

        # Retry patterns (use elif to avoid double-counting overlapping phrases)
        full_text_lower = full_text.lower()
        if 'let me try again' in full_text_lower:
            self.retry_patterns['let me try again'] += 1
        elif 'try again' in full_text_lower:
            self.retry_patterns['try again'] += 1

        if 'i need to fix' in full_text_lower:
            self.retry_patterns['I need to fix'] += 1
        elif 'let me fix' in full_text_lower:
            self.retry_patterns['let me fix'] += 1

    def categorize_fixes(self) -> dict[str, list[str]]:
        """Categorize fix contexts by type."""
        categories = {
            'Type errors': [],
            'Import/Module issues': [],
            'Test failures': [],
            'Build/Compile errors': [],
            'Syntax errors': [],
            'Linting issues': [],
            'Missing/Undefined': [],
            'API/Function signature': [],
            'Formatting issues': [],
            'Logic errors': [],
            'Other': []
        }

        # Deduplicate before categorizing
        unique_contexts = deduplicate_contexts(self.fix_contexts)

        for ctx in unique_contexts:
            ctx_lower = ctx.lower()

            # Use elif to ensure each item goes into exactly one category
            if 'type' in ctx_lower and ('error' in ctx_lower or 'mismatch' in ctx_lower):
                categories['Type errors'].append(ctx)
            elif 'import' in ctx_lower or 'module' in ctx_lower or 'require' in ctx_lower:
                categories['Import/Module issues'].append(ctx)
            elif 'test' in ctx_lower and ('fail' in ctx_lower or 'assert' in ctx_lower or 'expect' in ctx_lower):
                categories['Test failures'].append(ctx)
            elif 'compile' in ctx_lower or 'build' in ctx_lower:
                categories['Build/Compile errors'].append(ctx)
            elif 'syntax' in ctx_lower or 'parse' in ctx_lower or 'unexpected token' in ctx_lower:
                categories['Syntax errors'].append(ctx)
            elif any(x in ctx_lower for x in ['lint', 'eslint', 'pylint', 'flake8', 'rubocop', 'detekt']):
                categories['Linting issues'].append(ctx)
            elif any(x in ctx_lower for x in ['undefined', 'not defined', 'missing', 'unresolved', 'not found', 'does not exist']):
                categories['Missing/Undefined'].append(ctx)
            elif any(x in ctx_lower for x in ['parameter', 'argument', 'signature', 'overload', 'arity']):
                categories['API/Function signature'].append(ctx)
            elif any(x in ctx_lower for x in ['format', 'indent', 'whitespace', 'trailing', 'spacing']):
                categories['Formatting issues'].append(ctx)
            elif any(x in ctx_lower for x in ['logic', 'wrong', 'incorrect', 'bug', 'issue']):
                categories['Logic errors'].append(ctx)
            else:
                categories['Other'].append(ctx)

        return categories

    def analyze_all(self, top_n: int = 25):
        """Analyze all session files."""
        files = self.get_session_files(top_n)
        if not files:
            print(f"No session files found in {self.session_dir}", file=sys.stderr)
            return

        print(f"Analyzing {len(files)} session files...", file=sys.stderr)

        for filename, size in files:
            self.analyze_session(filename)

        self.sessions_analyzed = len(files)

        # Detect and flag outlier sessions (likely contain analysis output)
        for session, count in self.build_failures.items():
            if count > self.BUILD_FAILURE_OUTLIER_THRESHOLD:
                self.outlier_sessions.append(session)

        # Remove outlier sessions from build_failures to get accurate counts
        for session in self.outlier_sessions:
            del self.build_failures[session]

        if self.outlier_sessions:
            print(f"Note: {len(self.outlier_sessions)} session(s) excluded as outliers (likely contain analysis output)", file=sys.stderr)

    def generate_report(self) -> str:
        """Generate a text report of the analysis."""
        lines = []
        lines.append("=" * 70)
        lines.append("CLAUDE CODE SESSION ERROR ANALYSIS REPORT")
        lines.append("=" * 70)

        # 1. Build Failures
        lines.append("\n" + "=" * 70)
        lines.append("1. BUILD FAILURES")
        lines.append("=" * 70)
        total_build_fails = sum(self.build_failures.values())
        lines.append(f"Total BUILD FAILED occurrences: {total_build_fails}")
        if self.outlier_sessions:
            lines.append(f"(Excluded {len(self.outlier_sessions)} outlier session(s) with suspicious counts)")
        lines.append("\nTop sessions with build failures:")
        for session, count in sorted(self.build_failures.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {session}: {count}")

        # 2. Retry Patterns
        lines.append("\n" + "=" * 70)
        lines.append("2. RETRY PATTERNS")
        lines.append("=" * 70)
        for pattern, count in self.retry_patterns.most_common():
            lines.append(f"  '{pattern}': {count} occurrences")

        # 3. Fix Categories
        lines.append("\n" + "=" * 70)
        lines.append("3. WHAT THE AGENT HAD TO FIX (CATEGORIZED)")
        lines.append("=" * 70)
        categories = self.categorize_fixes()
        for category, items in sorted(categories.items(), key=lambda x: -len(x[1])):
            if items:
                lines.append(f"\n### {category} ({len(items)} occurrences) ###")
                seen = set()
                count = 0
                for item in items:
                    item_clean = item[:140]
                    if item_clean not in seen and count < 3:
                        seen.add(item_clean)
                        lines.append(f"  - {item_clean}...")
                        count += 1

        # 4. Recommendations
        lines.append("\n" + "=" * 70)
        lines.append("4. RECOMMENDATIONS FOR CLAUDE.md")
        lines.append("=" * 70)
        lines.extend(self._generate_recommendations())

        return '\n'.join(lines)

    def _generate_recommendations(self) -> list[str]:
        """Generate recommendations based on analysis."""
        recommendations = []
        categories = self.categorize_fixes()

        # Sort categories by count to prioritize recommendations
        sorted_categories = sorted(
            [(k, v) for k, v in categories.items() if v and k != 'Other'],
            key=lambda x: -len(x[1])
        )

        # Based on build failures
        total_build_fails = sum(self.build_failures.values())
        if total_build_fails > 10:
            recommendations.append("\n## Build Verification ##")
            recommendations.append("Add to CLAUDE.md:")
            recommendations.append("  - Run build commands after making changes to catch errors early")
            recommendations.append("  - Verify compilation succeeds before moving to next task")

        # Based on retry patterns
        total_retries = sum(self.retry_patterns.values())
        if total_retries > 30:
            recommendations.append("\n## Reduce Iteration Cycles ##")
            recommendations.append("Add to CLAUDE.md:")
            recommendations.append("  - Read existing code patterns before implementing new features")
            recommendations.append("  - Run incremental builds to catch errors early")

        # Generate recommendations for top categories
        for category, items in sorted_categories[:5]:  # Top 5 categories
            count = len(items)
            if count < 2:  # Skip categories with very few items
                continue

            if category == 'Logic errors':
                recommendations.append(f"\n## Logic Errors ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Carefully review business logic before implementation")
                recommendations.append("  - Consider edge cases and state transitions")
                recommendations.append("  - Verify ViewModel/state management patterns")

            elif category == 'Linting issues':
                recommendations.append(f"\n## Linting/Static Analysis ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Run linter before committing (detekt, eslint, etc.)")
                recommendations.append("  - Keep functions concise; extract helpers for complex logic")
                recommendations.append("  - Follow project's established code style")

            elif category == 'API/Function signature':
                recommendations.append(f"\n## API/Function Signatures ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Check function signatures before calling")
                recommendations.append("  - Use rememberUpdatedState for lambdas in effects")
                recommendations.append("  - Verify parameter types match expected signatures")

            elif category == 'Type errors':
                recommendations.append(f"\n## Type Errors ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Verify type compatibility before assignments")
                recommendations.append("  - Check import sources for similarly-named types")
                recommendations.append("  - Use explicit type annotations when ambiguous")

            elif category == 'Import/Module issues':
                recommendations.append(f"\n## Import/Module Issues ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Verify imports exist before using them")
                recommendations.append("  - Check correct package for similarly-named classes")
                recommendations.append("  - Remove unused imports after refactoring")

            elif category == 'Test failures':
                recommendations.append(f"\n## Test Failures ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Run tests after each significant change")
                recommendations.append("  - Verify test expectations match implementation")
                recommendations.append("  - Update tests when changing behavior")

            elif category == 'Build/Compile errors':
                recommendations.append(f"\n## Compilation Errors ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Compile incrementally to catch errors early")
                recommendations.append("  - Fix all compiler errors before proceeding")

            elif category == 'Syntax errors':
                recommendations.append(f"\n## Syntax Errors ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Check syntax before saving files")
                recommendations.append("  - Verify bracket/parenthesis matching")

            elif category == 'Missing/Undefined':
                recommendations.append(f"\n## Missing/Undefined References ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Verify variables/functions exist before using")
                recommendations.append("  - Check scope and visibility of referenced items")

            elif category == 'Formatting issues':
                recommendations.append(f"\n## Formatting Issues ({count} occurrences) ##")
                recommendations.append("Add to CLAUDE.md:")
                recommendations.append("  - Run formatter before committing")
                recommendations.append("  - Follow project's formatting conventions")

        # If we have "Other" as the largest category, note it
        other_count = len(categories.get('Other', []))
        if other_count > 20 and (not sorted_categories or other_count > len(sorted_categories[0][1])):
            recommendations.append(f"\n## General Issues ({other_count} uncategorized) ##")
            recommendations.append("Add to CLAUDE.md:")
            recommendations.append("  - Review error messages carefully before fixing")
            recommendations.append("  - Understand root cause before applying fixes")

        if not recommendations:
            recommendations.append("\nNo specific recommendations - error patterns are within normal range.")

        return recommendations

    def to_json(self) -> dict:
        """Export analysis results as JSON."""
        categories = self.categorize_fixes()
        return {
            'session_dir': str(self.session_dir),
            'build_failures': dict(self.build_failures),
            'retry_patterns': dict(self.retry_patterns),
            'fix_categories': {k: {'count': len(v), 'examples': v[:3]} for k, v in categories.items() if v},
            'totals': {
                'build_failures': sum(self.build_failures.values()),
                'retry_messages': sum(self.retry_patterns.values()),
                'fix_contexts': len(self.fix_contexts),
                'unique_fix_contexts': sum(len(v) for v in categories.values()),
                'sessions_analyzed': self.sessions_analyzed,
                'outlier_sessions_excluded': len(self.outlier_sessions)
            },
            'outlier_sessions': self.outlier_sessions,
            'recommendations': self._generate_recommendations()
        }


def main():
    parser = argparse.ArgumentParser(description='Analyze Claude Code session transcripts')
    parser.add_argument('--cwd', type=str, default=os.getcwd(),
                        help='Working directory to detect project sessions from')
    parser.add_argument('--top', type=int, default=25,
                        help='Analyze top N largest session files')
    parser.add_argument('--output', choices=['text', 'json'], default='json',
                        help='Output format')
    parser.add_argument('--exclude', type=str, default='',
                        help='Comma-separated session IDs to exclude')
    parser.add_argument('--list-dirs', action='store_true',
                        help='List all available session directories')

    args = parser.parse_args()

    # List available directories if requested
    if args.list_dirs:
        dirs = find_all_session_dirs()
        if dirs:
            print("Available session directories:", file=sys.stderr)
            for d in sorted(dirs):
                print(f"  {d}", file=sys.stderr)
        else:
            print("No session directories found in ~/.claude/projects/", file=sys.stderr)
        return

    session_dir = cwd_to_session_dir(args.cwd)

    if session_dir is None:
        all_dirs = find_all_session_dirs()
        print(f"No session directory found for: {args.cwd}", file=sys.stderr)
        print(f"Searched in: ~/.claude/projects/", file=sys.stderr)
        if all_dirs:
            print(f"\nAvailable directories ({len(all_dirs)}):", file=sys.stderr)
            for d in sorted(all_dirs)[:10]:
                print(f"  {d}", file=sys.stderr)
            if len(all_dirs) > 10:
                print(f"  ... and {len(all_dirs) - 10} more", file=sys.stderr)
        # Return empty JSON for programmatic use
        if args.output == 'json':
            print(json.dumps({
                'error': 'no_session_dir',
                'cwd': args.cwd,
                'available_dirs': all_dirs[:10]
            }, indent=2))
        return

    exclude = [x.strip() for x in args.exclude.split(',') if x.strip()]

    analyzer = SessionAnalyzer(session_dir, exclude_sessions=exclude)
    analyzer.analyze_all(top_n=args.top)

    if args.output == 'json':
        print(json.dumps(analyzer.to_json(), indent=2))
    else:
        print(analyzer.generate_report())


if __name__ == '__main__':
    if '--test' in sys.argv:
        import unittest

        class TestIsMetaContent(unittest.TestCase):
            """Tests for is_meta_content function."""

            def test_grep_command(self):
                self.assertTrue(is_meta_content("grep 'pattern' file.txt"))

            def test_shell_script(self):
                self.assertTrue(is_meta_content("#!/bin/bash\necho hello"))

            def test_python_inline(self):
                self.assertTrue(is_meta_content("python3 -c 'print(1)'"))

            def test_pipe_command(self):
                self.assertTrue(is_meta_content("cat file | grep error | wc -l"))

            def test_analysis_output(self):
                self.assertTrue(is_meta_content("### Other (100 occurrences) ###"))

            def test_normal_text(self):
                self.assertFalse(is_meta_content("I need to fix the type error"))

            def test_normal_fix_context(self):
                self.assertFalse(is_meta_content("Let me fix the undefined variable"))

        class TestDeduplicateContexts(unittest.TestCase):
            """Tests for deduplicate_contexts function."""

            def test_empty_list(self):
                self.assertEqual(deduplicate_contexts([]), [])

            def test_no_duplicates(self):
                contexts = ['error one', 'error two', 'error three']
                result = deduplicate_contexts(contexts)
                self.assertEqual(len(result), 3)

            def test_exact_duplicates(self):
                contexts = ['same error here', 'same error here', 'different error']
                result = deduplicate_contexts(contexts)
                self.assertEqual(len(result), 2)

            def test_prefix_duplicates(self):
                contexts = [
                    'I need to fix the type error in function foo',
                    'I need to fix the type error in function bar',
                    'Different error entirely'
                ]
                result = deduplicate_contexts(contexts, similarity_threshold=30)
                self.assertEqual(len(result), 2)

        class TestCwdToSessionDir(unittest.TestCase):
            """Tests for cwd_to_session_dir function."""

            def test_nonexistent_path_returns_none(self):
                result = cwd_to_session_dir('/nonexistent/path/project')
                self.assertIsNone(result)

            def test_fallback_matches_project_name(self):
                # If there's a dir ending with the project name, it should match
                # This tests the fallback logic (can't easily test without mocking)
                result = cwd_to_session_dir('/some/other/path')
                # Should return None since no matching dir exists
                self.assertIsNone(result)

        class TestFindAllSessionDirs(unittest.TestCase):
            """Tests for find_all_session_dirs function."""

            def test_returns_list(self):
                result = find_all_session_dirs()
                self.assertIsInstance(result, list)

        class TestExtractTextRecursive(unittest.TestCase):
            """Tests for extract_text_recursive function."""

            def test_string(self):
                result = extract_text_recursive('hello')
                self.assertEqual(result, ['hello'])

            def test_list(self):
                result = extract_text_recursive(['a', 'b', 'c'])
                self.assertEqual(result, ['a', 'b', 'c'])

            def test_dict(self):
                result = extract_text_recursive({'key': 'value', 'other': 'text'})
                self.assertIn('value', result)
                self.assertIn('text', result)

            def test_nested(self):
                obj = {'level1': {'level2': ['deep', 'text']}}
                result = extract_text_recursive(obj)
                self.assertIn('deep', result)
                self.assertIn('text', result)

            def test_mixed_types(self):
                obj = {'text': 'hello', 'number': 42, 'list': ['a', 'b']}
                result = extract_text_recursive(obj)
                self.assertIn('hello', result)
                self.assertIn('a', result)
                self.assertNotIn(42, result)

        class TestFindTextWithContext(unittest.TestCase):
            """Tests for find_text_with_context function."""

            def test_finds_pattern(self):
                obj = 'This is an error message here'
                results = find_text_with_context(obj, ['error'])
                self.assertEqual(len(results), 1)
                self.assertIn('error', results[0])

            def test_case_insensitive(self):
                obj = 'This has an ERROR in it'
                results = find_text_with_context(obj, ['error'])
                self.assertEqual(len(results), 1)

            def test_nested_object(self):
                obj = {'message': {'content': 'Found an error here'}}
                results = find_text_with_context(obj, ['error'])
                self.assertEqual(len(results), 1)

            def test_no_match(self):
                obj = 'No issues found'
                results = find_text_with_context(obj, ['error'])
                self.assertEqual(len(results), 0)

        class TestSessionAnalyzer(unittest.TestCase):
            """Tests for SessionAnalyzer class."""

            def setUp(self):
                self.analyzer = SessionAnalyzer('/nonexistent/path')

            def test_init(self):
                self.assertEqual(self.analyzer.sessions_analyzed, 0)
                self.assertEqual(len(self.analyzer.build_failures), 0)

            def test_get_session_files_nonexistent(self):
                files = self.analyzer.get_session_files()
                self.assertEqual(files, [])

            def test_analyze_message_build_failure(self):
                msg = {'content': 'BUILD FAILED in 5s'}
                self.analyzer._analyze_message(msg, 'test-session')
                self.assertEqual(self.analyzer.build_failures['test-session'], 1)

            def test_analyze_message_multiple_build_failures(self):
                msg = {'content': 'BUILD FAILED\nRetrying...\nBUILD FAILED again'}
                self.analyzer._analyze_message(msg, 'test-session')
                self.assertEqual(self.analyzer.build_failures['test-session'], 2)

            def test_analyze_message_retry_pattern_try_again(self):
                msg = {'content': 'Let me try again with a different approach'}
                self.analyzer._analyze_message(msg, 'test-session')
                self.assertEqual(self.analyzer.retry_patterns['let me try again'], 1)
                # Should NOT also count 'try again' due to elif
                self.assertEqual(self.analyzer.retry_patterns['try again'], 0)

            def test_analyze_message_retry_pattern_no_overlap(self):
                msg = {'content': 'I will try again now'}
                self.analyzer._analyze_message(msg, 'test-session')
                self.assertEqual(self.analyzer.retry_patterns['try again'], 1)
                self.assertEqual(self.analyzer.retry_patterns['let me try again'], 0)

            def test_analyze_message_fix_pattern_no_overlap(self):
                msg = {'content': 'I need to fix this error'}
                self.analyzer._analyze_message(msg, 'test-session')
                self.assertEqual(self.analyzer.retry_patterns['I need to fix'], 1)
                self.assertEqual(self.analyzer.retry_patterns['let me fix'], 0)

            def test_analyze_message_fix_context(self):
                msg = {'content': 'I need to fix this type error in the function'}
                self.analyzer._analyze_message(msg, 'test-session')
                self.assertEqual(len(self.analyzer.fix_contexts), 1)

            def test_analyze_message_filters_meta_content(self):
                msg = {'content': "grep 'I need to fix' file.jsonl | wc -l"}
                self.analyzer._analyze_message(msg, 'test-session')
                # Should NOT add this as it's meta-content
                self.assertEqual(len(self.analyzer.fix_contexts), 0)

        class TestCategorizeFixes(unittest.TestCase):
            """Tests for categorize_fixes method."""

            def setUp(self):
                self.analyzer = SessionAnalyzer('/nonexistent/path')

            def test_type_error_category(self):
                self.analyzer.fix_contexts = ['Type error: expected string got int']
                categories = self.analyzer.categorize_fixes()
                self.assertEqual(len(categories['Type errors']), 1)

            def test_import_category(self):
                self.analyzer.fix_contexts = ['Missing import statement']
                categories = self.analyzer.categorize_fixes()
                self.assertEqual(len(categories['Import/Module issues']), 1)

            def test_test_failure_category(self):
                self.analyzer.fix_contexts = ['The test is failing because of assertion']
                categories = self.analyzer.categorize_fixes()
                self.assertEqual(len(categories['Test failures']), 1)

            def test_build_category(self):
                self.analyzer.fix_contexts = ['Build error in compilation']
                categories = self.analyzer.categorize_fixes()
                self.assertEqual(len(categories['Build/Compile errors']), 1)

            def test_missing_undefined_category(self):
                self.analyzer.fix_contexts = ['The variable is undefined here']
                categories = self.analyzer.categorize_fixes()
                self.assertEqual(len(categories['Missing/Undefined']), 1)

            def test_linting_category(self):
                self.analyzer.fix_contexts = ['The eslint rule is complaining about this']
                categories = self.analyzer.categorize_fixes()
                self.assertEqual(len(categories['Linting issues']), 1)

            def test_deduplication(self):
                # Exact same prefix (50 chars) should be deduplicated
                self.analyzer.fix_contexts = [
                    'I need to fix the type error in the function that handles user input validation',
                    'I need to fix the type error in the function that processes data differently',
                ]
                categories = self.analyzer.categorize_fixes()
                total = sum(len(v) for v in categories.values())
                self.assertEqual(total, 1)  # Should be deduplicated to 1

            def test_other_category(self):
                self.analyzer.fix_contexts = ['Something unrelated to known patterns']
                categories = self.analyzer.categorize_fixes()
                self.assertEqual(len(categories['Other']), 1)

        class TestToJson(unittest.TestCase):
            """Tests for to_json method."""

            def setUp(self):
                self.analyzer = SessionAnalyzer('/nonexistent/path')

            def test_sessions_analyzed_initially_zero(self):
                result = self.analyzer.to_json()
                self.assertEqual(result['totals']['sessions_analyzed'], 0)

            def test_structure(self):
                result = self.analyzer.to_json()
                self.assertIn('session_dir', result)
                self.assertIn('build_failures', result)
                self.assertIn('retry_patterns', result)
                self.assertIn('totals', result)
                self.assertIn('recommendations', result)

        # Run the tests
        unittest.main(argv=[''], exit=True, verbosity=2)
    else:
        main()
