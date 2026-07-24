#!/usr/bin/env bash
# SQLite backup script for Networa
# Usage: ./scripts/backup.sh [backup_dir] [keep_days]
#   backup_dir  - destination directory (default: ./backups)
#   keep_days   - days of backups to retain (default: 30, 0 = keep all)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DB_PATH="${DB_PATH:-$PROJECT_DIR/data/networth.db}"
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
KEEP_DAYS="${2:-30}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/networth_$TIMESTAMP.db"

if [ ! -f "$DB_PATH" ]; then
    echo "Error: database not found at $DB_PATH" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# Use SQLite online backup via the .backup command (safe with WAL mode)
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "Backup saved: $BACKUP_FILE ($SIZE)"

# Prune old backups
if [ "$KEEP_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -name "networth_*.db" -mtime +"$KEEP_DAYS" -delete
    echo "Pruned backups older than $KEEP_DAYS days"
fi
