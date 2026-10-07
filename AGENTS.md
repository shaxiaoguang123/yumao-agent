# AGENTS.md

## Long-running tasks

- For long-running commands, wait for the command to finish or report completion; do not poll frequently or stop a healthy process.
- If a long-running command needs a status check because it has produced no output, check after 5 minutes, then 10 minutes, then 20 minutes, and every 20 minutes thereafter.
- Keep waiting while the task is healthy. Interrupt only for a clear error, a hang, or a user request to stop.

## Downloads and network

- If dependency, model, data, or software downloads are slow, prefer an already configured Clash proxy, a reliable regional mirror, or another stable package source.
- Do not stop a download solely because it is slow.

## Conda environments

- Use the existing `test` environment for ordinary Python projects.
- Use the existing `pt` environment for deep learning, PyTorch, or machine learning projects.
- Activate the appropriate environment before running project commands. Do not create a new Conda environment unless a real dependency conflict or explicit version requirement calls for one.

## Subagents

- If subagents are needed, use **only** the model `gpt-6-luna`. Do not use another model for a subagent.
- Any reasoning effort supported by that model is allowed, including `max`.
- This restriction applies to every subagent and follow-up delegation in this repository, including in current and future worktrees. Verify this file is present at the repository root before creating a subagent in a worktree.
