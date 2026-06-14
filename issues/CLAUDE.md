# Issues Directory

This directory contains screenshots of bugs/issues from the Telegram bot or dashboard. Screenshots are taken from the user's phone or browser and dropped here for investigation.

## Screenshot date convention

Screenshot filenames contain the date they were taken, e.g. `Screenshot_20260528_120010_Telegram.jpg` means the screenshot was taken on **2026-05-28**.

## After fixing an issue

When a plan is executed to fix an issue from a screenshot, **rename the screenshot** to append the plan/branch name with a `--` separator. Example: `why-no-history.jpg` becomes `why-no-history--fix-conversational-history.jpg`. This links the issue to its fix for future reference.

## Before investigating a screenshot

1. **Extract the date** from the filename (format: `YYYYMMDD`).
2. **Check git log** for commits in the relevant submodule (`health_tracker` or `dashboard`) that were pushed **after** that date.
3. If a commit after the screenshot date clearly addresses the issue shown in the screenshot, **inform the user** that the issue appears to have been fixed in that commit (cite the commit hash and message) and ask whether it's still reproducing before doing any further investigation.
4. Only proceed with debugging if there is no matching fix, or the user confirms the issue persists.
