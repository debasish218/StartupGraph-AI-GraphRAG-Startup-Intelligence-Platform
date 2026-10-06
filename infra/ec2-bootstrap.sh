#!/usr/bin/env bash
# One-time setup of an Ubuntu 22.04/24.04 EC2 instance (t3.large or bigger recommended).
# Usage (on the instance):  curl -fsSL <raw url of this file> | sudo bash -s -- <git-repo-url>
set -euo pipefail

REPO_URL="${1:?usage: ec2-bootstrap.sh <git-repo-url>}"
APP_DIR=/opt/startupgraph
APP_USER="${SUDO_USER:-ubuntu}"

apt-get update -y
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$APP_USER"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  sed -i "s/^NEO4J_PASSWORD=.*/NEO4J_PASSWORD=$(openssl rand -hex 16)/" "$APP_DIR/.env"
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" "$APP_DIR/.env"
  sed -i "s/^ADMIN_API_KEY=.*/ADMIN_API_KEY=$(openssl rand -hex 24)/" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "Created $APP_DIR/.env with random secrets. Add LLM/embedding API keys there if needed."
fi

cd "$APP_DIR"
sudo -u "$APP_USER" docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
echo "StartupGraph AI is starting on port 80. Open the EC2 security group for HTTP (and HTTPS behind a proxy/ALB)."
