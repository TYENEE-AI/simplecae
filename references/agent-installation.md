# Local Agent installation

SimpleCAE uses a portable `SKILL.md` directory and a local Python CLI. The host
Agent needs file reading and terminal execution; there is no vendor-specific
MCP server, browser automation dependency or model API key inside SimpleCAE.

From a qualified source release, preview the destination, then install:

```text
python scripts/install_local.py --agent claude --show-target
python scripts/install_local.py --agent claude
```

Replace `claude` with the host below. Existing skill-managed files receive a
recoverable backup; runtime, solver downloads, outputs and unrelated root files
are preserved. A source checkout without current qualification cannot masquerade
as a tested release. Complete runtime setup in the installed folder separately.

| Host flag | Default user discovery root |
|---|---|
| `codex` | `$CODEX_HOME/skills`, otherwise `~/.codex/skills` |
| `claude` | `$CLAUDE_CONFIG_DIR/skills`, otherwise `~/.claude/skills` |
| `deepseek` | `~/.agents/skills` |
| `omp` | `~/.omp/agent/skills` |
| `pi` | `~/.agents/skills` |

The installer creates `simplecae/SKILL.md` below the root. For a custom host
profile or project installation, use `--skills-root PATH`; it takes precedence
over the host default. In particular, OMP named profiles may use a different
root. Do not install another copy with the same name without checking host
precedence; it can keep loading an older copy.

Claude Code documents personal/project `.claude/skills` directories.
[Official Claude Code instructions](https://code.claude.com/docs/en/skills)

DeepSeek Harness supports project `.dsh/skills`, `.agents/skills`, and user
skill roots. Pi also supports user/project `.agents/skills`. Both can use the
same portable folder.
[DeepSeek Harness discovery](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md),
[Pi skill documentation](https://pi.dev/docs/latest/skills)

OMP uses user `~/.omp/agent/skills` and project `.omp/skills`, with separate
profile/configuration rules.
[OMP discovery documentation](https://github.com/can1357/oh-my-pi/blob/main/docs/config-usage.md)

After installation, reload/restart host skill discovery and ask it to use
SimpleCAE explicitly. First verify `python -m simplecae --version` in the
configured runtime, then run the quickstart and an actual task. Discovery-path
compatibility is separate from an end-to-end test of a particular Agent/model;
the release evidence must state which hosts were actually exercised.
