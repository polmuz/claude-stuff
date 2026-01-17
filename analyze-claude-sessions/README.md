# analyze-claude-sessions

A Claude Code plugin that analyzes session transcripts to identify error patterns and suggest CLAUDE.md improvements.

## What It Does

This plugin scans your Claude Code session transcripts to find:

- **Build failures**: How often builds fail and in which sessions
- **Retry patterns**: How often the agent has to retry or fix things ("let me fix", "try again", etc.)
- **Fix categories**: Categorized list of what the agent had to fix:
  - Type errors
  - Import/Module issues
  - Test failures
  - Build/Compile errors
  - Syntax errors
  - Linting issues
  - Missing/Undefined references
  - API/Function signature issues
  - Formatting issues
  - Logic errors

Based on this analysis, it generates **data-driven recommendations** for your CLAUDE.md file to help future sessions avoid these patterns.

## Installation

See the [main claude-stuff README](../README.md) for installation options.

## Usage

Once the plugin is loaded, run:

```
/analyze-claude-sessions:analyze
```

This will:
1. Auto-detect the current project's session directory
2. Analyze the top 25 largest session files
3. Filter out meta-content and deduplicate similar issues
4. Present a summary of findings with occurrence counts
5. Generate specific, data-driven recommendations
6. Offer to add guidance to your CLAUDE.md

## Manual Script Usage

You can also run the analysis script directly:

```bash
# Analyze current project (JSON output)
python3 ./claude-stuff/analyze-claude-sessions/lib/analyze_sessions.py --cwd .

# Output as text report
python3 ./claude-stuff/analyze-claude-sessions/lib/analyze_sessions.py --cwd . --output text

# Analyze top 50 sessions
python3 ./claude-stuff/analyze-claude-sessions/lib/analyze_sessions.py --cwd . --top 50

# Exclude specific sessions
python3 ./claude-stuff/analyze-claude-sessions/lib/analyze_sessions.py --exclude "abc123,def456"

# Run tests
python3 ./claude-stuff/analyze-claude-sessions/lib/analyze_sessions.py --test
```

## Features

- **Smart filtering**: Automatically excludes meta-content (shell commands, previous analysis output)
- **Deduplication**: Groups similar fix contexts to avoid counting the same issue multiple times
- **Outlier detection**: Excludes sessions with suspiciously high counts (likely contain analysis output)
- **Data-driven recommendations**: Generates specific advice based on actual error frequencies
- **Multiple installation paths**: Works project-local, global, or via settings

## How It Works

Claude Code stores session transcripts in:
```
~/.claude/projects/{project-path-with-dashes}/
```

For example, `/home/user/myproject` sessions are stored in:
```
~/.claude/projects/-home-user-myproject/
```

The analyzer scans these JSONL files for error patterns using regex matching and text analysis.

## License

MIT - See [LICENSE](../LICENSE)
