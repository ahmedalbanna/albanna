#!/usr/bin/env bash
# Complete REA (Reverse Engineer Anything) installation script.
# Run as root on Ubuntu 24.04 (or adapt paths). Installs core REA, providers and MCP link for OpenCode.
set -euo pipefail

# ---------- 1. Core requirements ----------
sudo apt-get update -qq
sudo apt-get install -y curl unzip procps openjdk-21-jdk tshark binwalk sigrok-cli

# Node.js 22.x is required (already present in this environment).
node --version

# ---------- 2. Install REA CLI + MCP registration ----------
npm install -g rea-agents
rea --version

# ---------- 3. Install Hopper (optional provider) ----------
rea setup --yes --all-detected --install-hopper

# ---------- 4. Install Ghidra 12.1.4 (optional provider) ----------
mkdir -p /tmp/opencode
curl -L -o /tmp/opencode/ghidra.zip \
  "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip"
rm -rf /opt/ghidra_12.1.4_PUBLIC
cd /opt && unzip -q /tmp/opencode/ghidra.zip
export GHIDRA_INSTALL_DIR=/opt/ghidra_12.1.4_PUBLIC
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# ---------- 5. Install JADX + jadx-headless-mcp 0.7.1 ----------
curl -L -o /tmp/opencode/jadx.zip \
  "https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip"
rm -rf /opt/jadx && mkdir -p /opt/jadx
cd /opt/jadx && unzip -q /tmp/opencode/jadx.zip

curl -L -o /opt/jadx-headless-mcp-0.7.1-all.jar \
  "https://github.com/1013503897/jadx-headless-mcp/releases/download/v0.7.1/jadx-headless-mcp-0.7.1-all.jar"
export REA_JADX_MCP_JAR=/opt/jadx-headless-mcp-0.7.1-all.jar

# ---------- 6. Install Kuna decompiler ----------
curl -L -o /tmp/opencode/kuna.tar.gz \
  "https://github.com/Noelo-Lab/kuna/releases/download/v1.984/kuna-v1.984-linux-x86_64.tar.gz"
rm -rf /opt/kuna && mkdir -p /opt/kuna
tar -xzf /tmp/opencode/kuna.tar.gz -C /opt/kuna
export REA_KUNA_COMMAND=/opt/kuna/kuna-v1.984-linux-x86_64/kuna
chmod +x "$REA_KUNA_COMMAND"

# ---------- 7. Persist environment ----------
cat > /etc/profile.d/rea.sh <<'EOF'
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export GHIDRA_INSTALL_DIR=/opt/ghidra_12.1.4_PUBLIC
export HOPPER_LAUNCHER_PATH=/opt/hopper/bin/Hopper
export REA_JADX_MCP_JAR=/opt/jadx-headless-mcp-0.7.1-all.jar
export REA_KUNA_COMMAND=/opt/kuna/kuna-v1.984-linux-x86_64/kuna
export PATH=/opt/jadx/bin:/opt/hopper/bin:$JAVA_HOME/bin:$PATH
EOF
chmod +x /etc/profile.d/rea.sh
# shellcheck disable=SC1091
source /etc/profile.d/rea.sh

# ---------- 8. Link MCP with OpenCode ----------
rea setup --yes --all-detected

# ---------- 9. Verify ----------
rea doctor

echo "REA installation complete. Restart OpenCode to activate the MCP server."