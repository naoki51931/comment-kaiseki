#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
  echo "usage: $0 backups/file.dump" >&2
  exit 2
fi
sudo docker compose exec -T db pg_restore -U kifu -d kifu_comment --clean --if-exists < "$1"
