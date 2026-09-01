# Deploying to AWS Lightsail (fixed monthly price)

This folder contains everything to run the app on an always-on Lightsail VPS so
your local machine no longer needs to stay on during market hours.

## 1. Create the instance (one-time, in AWS console)
- Lightsail -> Create instance -> Linux -> **Ubuntu 24.04**
- Plan: **$10/month (2 GB RAM, 2 vCPU, 60 GB SSD)** — pandas/streamlit need >1 GB
- Attach a **static IP** (Networking tab; free while attached)

## 2. Copy the code to the server
From your PC (PowerShell), either clone your git repo on the server, or upload:
```powershell
scp -i <key.pem> -r C:\apps\ai_prompt_agent ubuntu@<static-ip>:/home/ubuntu/
```

## 3. Run the bootstrap
SSH in, then:
```bash
cd /home/ubuntu/ai_prompt_agent
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```
This sets IST timezone, installs deps, and registers two auto-restarting
`systemd` services:
- `streamlit.service`  -> the web UI on port 8501
- `algotrader.service` -> `python -m src.algo_auto_trader --loop` (24/7; its
  trade-window + hard-squareoff guards mean it only trades during market hours)

## 4. Firewall
Lightsail -> Networking -> add rule:
- If exposing Streamlit directly: **TCP 8501**, restrict Source to your home IP.
- If using Nginx (recommended): **TCP 80/443**, and keep 8501 closed.

## 5. Access
`http://<static-ip>:8501` (or `http://<static-ip>` behind Nginx).

## Secure access (recommended)
See `nginx-streamlit.conf` for putting Streamlit behind Nginx + Basic Auth +
optional HTTPS. The app can place real trades, so do not leave port 8501 open
to the world.

## Safety before going live
- Keep `dry_run=true` and `allow_live=false` in `algo_trade_config.json` until
  you have watched a full session run correctly on the server.
- Broker credentials live only on the server (do not commit them).
- Enable Lightsail **snapshots** for backup of `data/` and `downloads/`.

## Useful commands
```bash
sudo systemctl status  algotrader.service
sudo systemctl restart streamlit.service
sudo journalctl -u algotrader.service -f     # live logs
```

## Cost
~**$10/month flat**, no pay-as-you-go surprises. Snapshots add a small flat fee.
