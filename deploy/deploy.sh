#!/usr/bin/env bash
#
# One-time bootstrap for deploying ai_prompt_agent on an AWS Lightsail
# (Ubuntu 24.04) instance. Run as the default "ubuntu" user.
#
# Usage:
#   chmod +x deploy/deploy.sh
#   ./deploy/deploy.sh
#
set -euo pipefail

APP_DIR="/home/ubuntu/ai_prompt_agent"
VENV_DIR="${APP_DIR}/.venv"
PY="${VENV_DIR}/bin/python"

echo "==> 1/6  Setting timezone to Asia/Kolkata (IST) — required for trade-window guards"
sudo timedatectl set-timezone Asia/Kolkata
timedatectl | grep "Time zone"

echo "==> 2/6  Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git

echo "==> 3/6  Creating virtual environment"
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi

echo "==> 4/6  Installing Python dependencies"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> 5/6  Installing systemd services"
sudo cp "${APP_DIR}/deploy/streamlit.service"  /etc/systemd/system/streamlit.service
sudo cp "${APP_DIR}/deploy/algotrader.service" /etc/systemd/system/algotrader.service
sudo systemctl daemon-reload
sudo systemctl enable --now streamlit.service
sudo systemctl enable --now algotrader.service

echo "==> 6/6  Status"
sudo systemctl --no-pager status streamlit.service   | head -n 5 || true
sudo systemctl --no-pager status algotrader.service  | head -n 5 || true

echo
echo "Done. Streamlit UI: http://<your-static-ip>:8501"
echo "Logs:  sudo journalctl -u streamlit.service -f"
echo "       sudo journalctl -u algotrader.service -f"
echo
echo "SAFETY: keep dry_run=true / allow_live=false in algo_trade_config.json"
echo "        until you have validated the server run end-to-end."
