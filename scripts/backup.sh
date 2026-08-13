#!/bin/sh
set -eu
mkdir -p backups
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo docker compose exec -T db pg_dump -U kifu -d kifu_comment -Fc > "backups/kifu_comment-$timestamp.dump"
echo "backups/kifu_comment-$timestamp.dump"
