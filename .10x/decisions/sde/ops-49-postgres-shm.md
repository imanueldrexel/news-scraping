# OPS-49 #321: Postgres /dev/shm 64 MB → 1 GB (2026-10-12)

**Trigger:** the owner's Telegram: "Filter drift audit (OPS-18) FAILED, exit 1". `audit_filter_drift.py --dry-run` reproduced it as `DiskFull: could not resize shared memory segment … to 16777216 bytes`. That is the container's default 64 MB `/dev/shm` running out for a 2-worker parallel hash join. The disk was 20% used. Last week's run of the same query passed; the tables grew past the limit.

**Done (owner-approved, option 1 of 3):**
- `backup_db.py`: `newsaggregator_20261012T010159Z.dump` (396.6 MB, verified).
- `docker/docker-compose.yaml`: `shm_size: 1gb`, with a comment saying why.
- `docker compose up -d`: recreated 08:03:05–08:03:48 WIB, healthy. `ShmSize=1073741824`, mount `newsaggregator_pgdata`, `/dev/shm` 1.0G.
- Row counts of 7 tables identical before and after.
- `audit_filter_drift.py --dry-run` OK. The real run: saved 0.95, rejected 0.78, topic 0.75, 27 disagreements, no alerts, `crawler_health/filter_drift_2026-10-12.json`, exit 0.
- OPERATIONS.md "Database: container, backup, restore" gains a "Shared memory (OPS-49)" paragraph.

**Not chosen:**
- `max_parallel_workers_per_gather=0`: loses parallel scans everywhere.
- Per-query `SET LOCAL`: leaves every other query exposed.

**Note:** topic agreement dropped from 0.815 to 0.747 week on week. There is no alert threshold on topic; worth a look if it falls again.
