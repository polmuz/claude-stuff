# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Claude Code plugin marketplace containing reusable plugins. The marketplace is defined in `.claude-plugin/marketplace.json` and individual plugins live in subdirectories with their own `.claude-plugin/plugin.json` manifests.

## Before Committing

Always validate the marketplace and all plugins:

```bash
# Validate marketplace
claude plugin validate .

# Validate each plugin
claude plugin validate ./analyze-claude-sessions

# Run tests for analyze-claude-sessions
python3 ./analyze-claude-sessions/lib/analyze_sessions.py --test
```

All validations must pass before pushing changes.

## Adding a New Plugin

1. Create a new directory: `my-plugin/`
2. Add `.claude-plugin/plugin.json` with required fields: `name`, `description`, `version`
3. Add commands in `my-plugin/commands/*.md`
4. Register in `.claude-plugin/marketplace.json` under `plugins` array
5. Validate both the plugin and marketplace before committing
