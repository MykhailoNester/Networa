#!/usr/bin/env bash
# SQLite backup script for Networa
# Usage: ./scripts/backup.sh [backup_dir] [keep_days]
#   backup_dir  - destination directory (default: ./backups)
#   keep_days   - days of backups to retain (default: 30, 0 = keep all)
#
# Which database gets backed up follows the app's own configuration:
#   DB_PATH=...        back up this exact file, whatever the app uses
#   DATABASE_PATH=...  same variable the app reads
#   DB_NAME=mine.db    a file under data/
#   (none of the above) data/networa.db, the app's default

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Resolve the same database the app would open: DATABASE_PATH wins, then DB_NAME
# under data/, then the app's own default. DB_PATH still overrides everything, for
# backing up a database the app is not currently configured for.
if [ -n "${DB_PATH:-}" ]; then
    :
elif [ -n "${DATABASE_PATH:-}" ]; then
    DB_PATH="$DATABASE_PATH"
else
    DB_PATH="$PROJECT_DIR/data/${DB_NAME:-networa.db}"
fi

BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
KEEP_DAYS="${2:-30}"

DB_STEM="$(basename "$DB_PATH")"
DB_STEM="${DB_STEM%.db}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/${DB_STEM}_$TIMESTAMP.db"

if [ ! -f "$DB_PATH" ]; then
    echo "Error: database not found at $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# Use SQLite online backup via the .backup command (safe with WAL mode)
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "Backup saved: $BACKUP_FILE ($SIZE)"

# Prune old backups (only ones for this same database)
if [ "$KEEP_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -name "${DB_STEM}_*.db" -mtime +"$KEEP_DAYS" -delete
    echo "Pruned backups older than $KEEP_DAYS days"
fi
