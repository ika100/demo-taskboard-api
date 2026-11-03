#!/usr/bin/env bash
# Run the built image like Kubernetes would (read-only root, tmpfs /tmp, numeric user) and probe it.
set -euo pipefail
name=demo-taskboard-api-smoke
port=18080
docker rm -f "$name" >/dev/null 2>&1 || true
docker run -d --name "$name" --read-only --tmpfs /tmp --user 10001:10001 -p "$port:8080" demo-taskboard-api:scan >/dev/null
trap 'docker logs "$name" 2>&1 | tail -20; docker rm -f "$name" >/dev/null 2>&1' EXIT
for _ in $(seq 1 30); do curl -fs "localhost:$port/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fs "localhost:$port/health"; echo
curl -fs "localhost:$port/ready"; echo
curl -fs -X POST "localhost:$port/tasks" -H 'content-type: application/json' -d '{"title":"smoke"}'; echo
curl -fs "localhost:$port/tasks"; echo
