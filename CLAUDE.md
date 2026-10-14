@AGENTS.md

## Claude Code notes

- `AGENTS.md` (imported above) is the single source of project knowledge. Put shared guidance
  there, not here, so other agents see it too.
- This machine is Linux; the script targets Windows and the company network. Verify with
  `python -m py_compile rebag_semi_automate_v5.py`. Don't try to launch Chrome or the sites.
- When the user pastes page HTML, put any working copies in the scratchpad, not the repo.
- Don't commit unless asked. `logs/` is tracked, so don't rewrite or delete existing log files.
