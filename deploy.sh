#!/usr/bin/env bash
set -e

IMAGE="<your-dockerhub-user>/pubsub-art-node:latest"
NODES=("art-node-1:<TS_IP_1>" "art-node-2:<TS_IP_2>" "art-node-3:<TS_IP_3>")
ALL_URLS="http://<TS_IP_1>:8000,http://<TS_IP_2>:8000,http://<TS_IP_3>:8000"

for entry in "${NODES[@]}"; do
  ID="${entry%%:*}"
  IP="${entry##*:}"
  echo "Deploying $ID ($IP)..."
  ssh ubuntu@$IP "
    docker pull $IMAGE &&
    docker stop art-node || true &&
    docker rm art-node || true &&
    docker run -d --name art-node --restart unless-stopped \
      -p 8000:8000 \
      -v /home/ubuntu/node_data:/data \
      -e NODE_ID=$ID \
      -e SEED_PEERS=$ALL_URLS \
      $IMAGE
  "
done