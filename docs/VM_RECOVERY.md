# Saumya AI VM Recovery Runbook

This document rebuilds the complete Saumya AI setup on a new Linux VM.

## 1. Architecture

There are two separate parts:

```text
Browser
  |
  v
quotation-ai-arena Docker container :7860
  |
  | http://host.docker.internal:3010/v1/chat/completions
  v
copilot-api.service on the VM host :3010
  |
  | gh auth token -> COPILOT_GITHUB_TOKEN
  v
GitHub Copilot CLI -> selected Copilot model
```

Important:

- Port `3010` is not the LLM Docker container. It is the host's `copilot-api.service`.
- The app container exposes port `7860`.
- Chat data and user accounts are stored in `data/chat_history.db`.
- `data/` and `logs/` are bind-mounted by Docker Compose and must be backed up.
- Never commit or paste GitHub tokens into Git, chat, screenshots, or this document.

## 2. Required VM packages

```bash
sudo apt update
sudo apt install -y git curl ca-certificates nodejs npm python3 openssl
```

Install Docker using the official Docker instructions if it is not already installed. Verify:

```bash
docker --version
docker compose version
git --version
node --version
python3 --version
```

## 3. GitHub CLI authentication

Install GitHub CLI (`gh`) if needed, then authenticate interactively:

```bash
gh auth login
gh auth status
```

Do not print the token. The systemd service reads it dynamically with `gh auth token`.

## 4. Install copilot-api on the VM host

Clone or restore the API wrapper:

```bash
cd /home/prashant
git clone <COPILOT_API_REPOSITORY_URL> copilot-api
cd /home/prashant/copilot-api
```

The wrapper must listen on `0.0.0.0:3010` and accept:

```text
POST /v1/chat/completions
```

Its request body uses:

```json
{
  "model": "gpt-5.4",
  "messages": [{"role": "user", "content": "Hello"}]
}
```

Test the CLI model IDs directly before starting the service:

```bash
copilot --model auto -p "Reply only: OK" --silent
copilot --model gpt-5.4 -p "Reply only: OK" --silent
```

Create the service:

```bash
sudo tee /etc/systemd/system/copilot-api.service >/dev/null <<'EOF'
[Unit]
Description=GitHub Copilot HTTP API Wrapper
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=prashant
Group=prashant
WorkingDirectory=/home/prashant/copilot-api
Environment=NODE_ENV=production
ExecStart=/bin/bash -lc 'export COPILOT_GITHUB_TOKEN="$(gh auth token)" && exec /usr/bin/node /home/prashant/copilot-api/server.js'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now copilot-api.service
sudo systemctl status copilot-api.service --no-pager
```

Verify the service is listening on all interfaces:

```bash
sudo ss -lntp | grep 3010
```

Expected:

```text
0.0.0.0:3010
```

Test the endpoint with the GitHub token. Do not share the output if it contains sensitive data:

```bash
curl -i \
  -H "Authorization: Bearer $(gh auth token)" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say hello"}],"stream":false}' \
  http://127.0.0.1:3010/v1/chat/completions
```

Expected result: `HTTP/1.1 200 OK`.

This wrapper does not implement `/v1/models`. A `404` from `/v1/models` is expected. Model availability is checked with the Copilot CLI instead.

## 5. Deploy quotation-ai-arena

```bash
cd /home/prashant
git clone git@github.com:shivatechdigital/aichatbot.git aichatbot
cd /home/prashant/aichatbot
cp .env.example .env
```

Set the real runtime values. Do not use the example token:

```bash
sed -i 's#^LLM_URL=.*#LLM_URL=http://host.docker.internal:3010/v1/chat/completions#' .env
sed -i '/^API_KEY=/d' .env
printf 'API_KEY=%s\n' "$(gh auth token)" >> .env
printf 'STORAGE_SECRET=%s\n' "$(openssl rand -hex 32)" >> .env
```

Set the verified model IDs. Keep this line synchronized with the discovery command output:

```bash
sed -i '/^COPILOT_MODELS=/d' .env
cat >> .env <<'EOF'
COPILOT_MODELS=gpt-5.4,gpt-5-mini,gpt-5.3-codex,gpt-5.4-mini,gpt-5.5,gpt-5.6-luna,gpt-6-astra,gpt-6-luna,gpt-6-sol,claude-sonnet-5,claude-fable-5,claude-fable-5.1,claude-haiku-4.5,claude-opus-4.7,claude-opus-4.8,claude-opus-5,claude-opus-5.5,gemini-3.5-flash,gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash,grok-4.5,grok-4.6,grok-4.7
EOF
```

Start the app:

```bash
docker compose up --build -d
```

Verify:

```bash
docker ps
docker exec quotation-ai-arena printenv LLM_URL
docker logs quotation-ai-arena --tail 100
```

Expected URL:

```text
http://host.docker.internal:3010/v1/chat/completions
```

Open:

```text
https://<YOUR_DOMAIN>/
```

## 6. First-use checklist

1. Open the app.
2. Type a prompt while logged out and press Send.
3. Sign up with an email and a password of at least 8 characters.
4. Confirm the original prompt returns to the composer.
5. Press Send again.
6. Create a second account in a private browser window.
7. Confirm the second account cannot see the first account's chats.
8. Test `Auto`, then one verified model such as `gpt-5.4`.
9. Test Stop while a response is streaming.
10. Test image/file upload and clipboard image paste.

## 7. Database backup

Always back up before pulling/rebuilding code:

```bash
cd /home/prashant/aichatbot
mkdir -p backups
cp data/chat_history.db "backups/chat_history-$(date +%Y%m%d-%H%M%S).db"
```

Also back up configuration without exposing it in chat:

```bash
cp .env "backups/env-$(date +%Y%m%d-%H%M%S).backup"
chmod 600 backups/*.backup
```

Do not put `.env` backups in a public Git repository.

## 8. Restore on a new VM

After deploying the app and stopping the container:

```bash
cd /home/prashant/aichatbot
docker compose down
cp /path/to/chat_history.db data/chat_history.db
chmod 600 data/chat_history.db
docker compose up -d
```

Restore the private `.env` backup separately:

```bash
cp /path/to/env.backup .env
chmod 600 .env
```

Never use `docker compose down -v` for this app. It can remove persistent data/volumes.

## 9. Updating the application

```bash
cd /home/prashant/aichatbot
cp data/chat_history.db "backups/chat_history-$(date +%Y%m%d-%H%M%S).db"
git pull
docker compose up --build -d
docker logs quotation-ai-arena --tail 100
```

Use `docker compose down` only when a clean restart is needed:

```bash
docker compose down
docker compose up --build -d
```

## 10. Model discovery

The API wrapper has no `/v1/models` route. Test candidate IDs through the Copilot CLI:

```bash
cd /home/prashant/copilot-api
chmod +x discover_copilot_models.sh
./discover_copilot_models.sh
```

Only IDs that print successfully should be placed in `COPILOT_MODELS` in `/home/prashant/aichatbot/.env`.

## 11. Troubleshooting

### App shows `3002` in the error

The deployment is using stale configuration. Confirm Compose forces port `3010`:

```bash
docker exec quotation-ai-arena printenv LLM_URL
```

If needed:

```bash
sed -i 's#^LLM_URL=.*#LLM_URL=http://host.docker.internal:3010/v1/chat/completions#' .env
docker compose up --build -d
```

### API returns `401`

The request is missing the Copilot bearer token. Confirm `.env` has a non-empty `API_KEY` and recreate the app container:

```bash
grep -q '^API_KEY=.' .env && echo configured
docker compose up --build -d
```

Never print the token.

### API returns `404` for `/v1/models`

Expected for this wrapper. Test `/v1/chat/completions` instead with the authenticated request from section 4.

### Container cannot reach port 3010

Check host binding and Docker host mapping:

```bash
sudo ss -lntp | grep 3010
docker exec quotation-ai-arena getent hosts host.docker.internal
```

The Compose file must contain:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### Service stopped

```bash
sudo systemctl status copilot-api.service --no-pager
sudo journalctl -u copilot-api.service -n 100 --no-pager
sudo systemctl restart copilot-api.service
```

### Chats disappeared

Check that the database file exists on the host and the bind mount is active:

```bash
ls -lh data/chat_history.db
docker inspect quotation-ai-arena --format '{{json .Mounts}}'
```

Never run `docker compose down -v` unless deleting all data is intentional.

## 12. Repository tests

Run before deployment:

```bash
python3 -m py_compile app/main.py app/database.py
python3 -m pytest -q
```

A successful deployment should show all tests passing and a running `quotation-ai-arena` container.



## 13. Backup:

Below command to take the backup of db

cd ~/aichatbot
mkdir -p backups
cp data/chat_history.db "backups/chat_history-$(date +%Y%m%d-%H%M%S).db"