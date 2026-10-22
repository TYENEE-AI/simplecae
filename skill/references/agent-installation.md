# Local Agent installation

SimpleCAE uses a portable `SKILL.md` directory and a local Python CLI. The host
Agent needs file reading and terminal execution; there is no vendor-specific
MCP server, browser automation dependency or model API key inside SimpleCAE.

From a source folder, install directly (destination preview is optional):

```text
python scripts/install_local.py --agent claude --show-target
python scripts/install_local.py --agent claude
```

Replace `claude` with the host below. Existing skill-managed files receive a
recoverable backup; runtime, solver downloads, outputs and unrelated root files
are preserved. Ordinary installation does not inspect release receipts or hash
source/backup files. Missing or stale receipts do not block installation. Do not
regenerate validation evidence, compare remote file hashes or rerun release suites
to install. Installation alone is not release qualification. Maintainers can opt
into source receipt verification with `--verify-release`; `--development` remains
a compatibility alias for ordinary installation, without a receipt requirement.
Complete runtime setup in the installed folder separately. Required entry files,
valid project metadata, path containment and copy errors still matter. Downloaded
solver archive integrity and numerical result validity checks are unchanged.
Bootstrap already performs its runtime check. Do not chain `runtime_ready.py`,
`doctor`, `addon_probe.py`, `pip check`, source-hash comparisons and quickstart as
additional ordinary-installation gates. Use the relevant diagnostic only when
setup reports a problem or the selected interpreter/solver changes. An addon
host's `sca addon check simplecae` is its native readiness entry point; a
standalone skill does not need the addon host installed just to run that check.
Bootstrap runs pip only for missing/incompatible Python dependencies or a
mismatched Python installation source. Native shared-library/loading failures
and unexpected inspection errors stop with a diagnostic without reinstalling
Python packages. After Python setup, readiness is checked again before proceeding.
Windows solver downloads have a 3000-second worker limit, configurable with
`bootstrap.ps1 -DownloadTimeoutSeconds SECONDS`. Failed downloads retain unique
`.partial` files; retrying uses a fresh file. Only a complete, SHA-256-verified
download becomes the reusable archive. A pre-existing invalid archive remains
rejected: preserve and move it aside before retrying. This download limit is
separate from the analysis budget and does not bound pip installation.

Install the skill files first, then bootstrap in that installed folder once. Do
not bootstrap both the checkout and the installed copy. When an Agent-bundled
Python lacks `venv`/`ensurepip`, locate an existing full 64-bit Python (for example
with `py -0p` on Windows) and pass `-Python PATH`; a working local environment can
be reused without replacing it or asking the user to reinstall Python.

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
For a DeepSeek Harness desktop project, run from the source folder and specify
the actual workspace root explicitly, for example on Windows:

```powershell
python scripts/install_local.py --skills-root 'C:\path\to\WorkSpace\.dsh\skills'
```

[DeepSeek Harness discovery](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md),
[Pi skill documentation](https://pi.dev/docs/latest/skills)

OMP uses user `~/.omp/agent/skills` and project `.omp/skills`, with separate
profile/configuration rules.
[OMP discovery documentation](https://github.com/can1357/oh-my-pi/blob/main/docs/config-usage.md)

After installation, reload/restart host skill discovery and ask it to use
SimpleCAE explicitly. If the host's selected runtime is uncertain, verify
`python -m simplecae --version` in that runtime, then proceed to the user task.
One quickstart example is optional;
full pytest, all examples and release/license audits are maintainer or learning
workflows, not installation gates. Discovery-path
compatibility is separate from an end-to-end test of a particular Agent/model;
the release evidence must state which hosts were actually exercised.
