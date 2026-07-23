# Multi-model delegation

- The primary `gpt-5.6-sol` agent owns decomposition, implementation plans, interface decisions, integration, and final verification.
- Use `gpt55_worker` for cost-conscious bounded coding, fixes, refactors, and focused tests.
- Use `sonnet5_worker` for bounded implementation, refactoring, and focused test tasks delegated to Claude Sonnet.
- Use `opus_worker` for architecture-sensitive changes, difficult debugging, and high-confidence review delegated to Claude Opus.
- Give every worker explicit file ownership, acceptance criteria, relevant commands, and a request to report changed files and verification results.
- Preserve unrelated user changes, never revert another agent's edits, and avoid concurrent writes to the same files.
- The primary agent must inspect worker changes and run integration-level checks before reporting completion.
- Do not authorize commits, pushes, pull requests, deployments, destructive operations, or external-system mutations unless the user explicitly requests them.
- Claude bridges must use `--permission-mode acceptEdits --allowedTools Read,Edit,Write,Bash,Glob,Grep`; never use `--dangerously-skip-permissions` or `bypassPermissions`.
- If a custom role is installed after the current task starts, open a new Codex task to refresh role discovery. A temporary `gpt-5.6-terra` bridge may be used only for the current task.
- If `gpt55_worker` is unavailable, use `C:\Users\cwson\AppData\Roaming\npm\codex.cmd exec --model gpt-5.5` only after `codex.cmd login status` succeeds; otherwise report that CLI authentication is required.
