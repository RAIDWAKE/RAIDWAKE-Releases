# Official EFT news feed

The `Official EFT news` workflow checks the game's official Steam announcements
feed every 15 minutes and sends new stories to Discord. GitHub may delay scheduled
runs; this is not an exact delivery-time guarantee. No always-on local computer is
required. Discord-only and social-only posts are outside this feed's coverage.

Each announcement gets one card with its original title, source link, publication
date and an official article image when available. It does not generate summaries,
ping members or repost the existing archive on first setup.

## Configuration

- Repository secret: `DISCORD_EFT_WEBHOOK`, scoped to the EFT updates channel.
- Workflow token: built-in `GITHUB_TOKEN`, used to save delivery state.
- Tracking branch: `eft-news-state`, file `eft-news-state.json`.
- The Discord bot token is not required or stored in GitHub.

The state branch contains public article URLs and delivery statuses only. The
workflow reads its executable code from `main`, never from that state branch.
Do not delete tracking state: it prevents duplicates across runs.

## Checks and recovery

Run `python -m unittest discover -s tests -v`. A manual workflow run normally just
checks for new stories. Select `connection_check` to send a one-time labelled test
card; it will not impersonate a release or post an old article as new.

Stories are marked `pending` before delivery, then `posted` after Discord confirms.
If delivery or the final state save fails, subsequent runs stop instead of risking
duplicates. Check the destination channel first. On the tracking branch, set that
story to `posted` if it arrived; otherwise remove its entry to retry. Do not remove
a pending entry without checking Discord. Never paste webhook URLs into issues.

Check Actions for failed or disabled runs. GitHub can disable scheduled workflows
in public repositories after 60 days without repository activity; re-enable the
workflow in Actions if that happens. Changing the Discord channel or revoking its
webhook requires updating the encrypted repository secret.
