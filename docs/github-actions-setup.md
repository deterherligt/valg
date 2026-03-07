# GitHub Actions Sync Setup

## Required repository variables (Settings → Variables → Repository variables)

| Variable | Example value | Description |
|---|---|---|
| `DATA_REPO` | `owner/valg-data` | Full name of the data repo |
| `ELECTION_FOLDER` | `/Folketingsvalg-1-2024` | Remote SFTP election folder path |

## Required secrets (Settings → Secrets → Actions)

| Secret | Default | Description |
|---|---|---|
| `DATA_REPO_TOKEN` | — | GitHub PAT with `contents:write` on the data repo |
| `VALG_SFTP_HOST` | `data.valg.dk` | SFTP host |
| `VALG_SFTP_PORT` | `22` | SFTP port |
| `VALG_SFTP_USER` | `Valg` | SFTP username |
| `VALG_SFTP_PASSWORD` | `Valg` | SFTP password |

## Notes

- The cron schedule runs every 5 minutes. GitHub may delay scheduled runs under load — this is acceptable.
- GitHub's minimum cron interval for scheduled workflows is 5 minutes.
- To disable sync between elections: go to Actions → SFTP Sync → disable workflow.
- To run manually: Actions → SFTP Sync → Run workflow.
- The `sync` command runs once per invocation (no loop). GitHub Actions handles the loop via cron.
