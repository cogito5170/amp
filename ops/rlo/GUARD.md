# W1 guard (rlo, enforce) — owned by AMP / baseline

The middle verification line (BD-161) for the W1 worker session. Baseline built it with the user's approval (BD-183). The user commits it because the classifier refused both AMP and baseline writing session settings.

- `.claude/settings.json`: SessionStart runs `install.sh`; every tool call (PreToolUse, matcher `*`) runs `guard.sh`.
- `install.sh`: installs pinned rlo-sdk[sensor] @ a152e14 (stage-8) into `~/.cache/amp-rlo-venv`. Idempotent.
- `guard.sh`: runs `python -m rlo.hooks --mode enforce` with `w1_guard.json`. Grants: `Bash` and `mcp__github__add_issue_comment`.
  - It is fail-closed: it denies when the venv is missing and the install fails, when the model is missing, when rlo exits nonzero, when rlo records no new verdict line, or when rlo prints non-JSON.
  - rlo allows by printing nothing. There is no clock override.
- `w1_guard.json` = AMP's `w1_strict` plus `ToolSearch`, `mcp__github__issue_read` (read) and `mcp__github__add_issue_comment` (external).
- rlo does not see Bash command content, file paths or argument values (for example, which issue a comment goes to).
- Baseline's check on fresh-time transcripts:
  - Pass: Bash, first call, after failure, Read, issue_read, add_issue_comment, ToolSearch.
  - Denied: WebFetch (A1), Agent (A1), an unknown Bash argument (A4), unknown health (D).
  - Fail-closed: missing model, uncreatable venv, garbage stdin, empty stdin.
- Do not edit `.claude/` or `ops/rlo/` from W1. Do not merge this into the AMP hub's branch.
- amp-w1-guard-2 (BD-194): added ReadNotifications (read) and mcp__claude-code-remote__send_message (external, granted). Without them W1 could not read AMP's messages (A1).
