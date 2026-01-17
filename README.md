# claude-stuff

A collection of Claude Code plugins by [polmuz](https://github.com/polmuz).

## Available Plugins

| Plugin | Command | Description |
|--------|---------|-------------|
| [analyze-claude-sessions](./analyze-claude-sessions/) | `/analyze-claude-sessions:analyze` | Analyze session transcripts to find error patterns and improve CLAUDE.md |

## Installation

### Option 1: From Claude Code (Recommended)

Add the marketplace and install the plugin:

```
/plugin marketplace add polmuz/claude-stuff
/plugin install analyze-claude-sessions@claude-stuff
```

### Option 2: Project-Local

Clone into your project directory:

```bash
git clone https://github.com/polmuz/claude-stuff.git
```

Then run Claude Code from your project - plugins are discovered automatically.

### Option 3: Global Installation

Clone to your home directory:

```bash
git clone https://github.com/polmuz/claude-stuff.git ~/claude-stuff
```

Or install to Claude's plugins directory:

```bash
mkdir -p ~/.claude/plugins
git clone https://github.com/polmuz/claude-stuff.git ~/.claude/plugins/claude-stuff
```

### Option 4: Add to Settings

Add to your `~/.claude/settings.json`:

```json
{
  "plugins": ["~/claude-stuff/analyze-claude-sessions"]
}
```

Or for all plugins:

```json
{
  "pluginDirs": ["~/claude-stuff"]
}
```

## Structure

```
claude-stuff/
├── analyze-claude-sessions/     # Session analyzer plugin
│   ├── .claude-plugin/
│   │   └── plugin.json
│   ├── commands/
│   │   └── analyze-claude-sessions.md
│   ├── lib/
│   │   └── analyze_sessions.py
│   └── README.md
├── LICENSE
└── README.md                    # This file
```

## Contributing

Feel free to open issues or PRs for:
- Bug fixes
- New plugins
- Improvements to existing plugins

## License

MIT
