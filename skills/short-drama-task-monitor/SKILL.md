---
name: short-drama-task-monitor
description: Read the recorded provider task ID, report progress and terminal status, and capture returned video links without downloading or judging the video.
---

# Task status and result link

Use only the provider and task ID already recorded in the RUN. Query status with bounded polling intervals; distinguish provider queue time from local execution time. Never submit a second task to recover an unknown or slow task.

Record provider responses as execution facts with timestamps and source evidence. On success, record the provider terminal state and returned output link(s), report them, and mark G6-S12 complete. Do not download, inspect local video files, run post-generation QA, edit the output, or publish it in this RUN.

On provider failure, record its error and report failure; do not retry. If status or output links cannot be verified, leave the RUN unresolved with the exact next read-only query or blocker. A provider success status is not a content QA verdict or user approval.
