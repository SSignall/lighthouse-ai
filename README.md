# Local Claw Plus Session Manager

**Your agents never crash from context overflow again.**

An automated session lifecycle manager and local model tool-calling fix for [OpenClaw](https://openclaw.io) agents. Built for teams running local models (Qwen, Mistral, Llama) where context windows fill up and tool calling breaks.

---

## The Problem

If you're running OpenClaw agents with local models, you've hit these walls:

### Context Overflow Crashes
Local models have fixed context windows (8K-128K tokens). Long-running agents — especially on Discord — accumulate conversation history in `.jsonl` session files until they exceed the model's limit. When that happens: **crash. Every time.**

The agent can't clear its own session. The gateway doesn't auto-rotate. You get a `Context overflow: prompt too large for the model` error and the agent goes dark until you manually intervene.

### Broken Tool Calling
Qwen2.5-Coder (and similar models) output tool calls as `<tools>` tags in the content field. But vLLM's built-in hermes parser expects `<tool_call>` tags. The result: **subagents spawn, receive no tool calls, and die with 0 output tokens.**

If you've seen `terminated` or `0 tokens` in your subagent logs — this is why.

---

## The Solution

### Session Autopilot
A lightweight daemon that monitors session file sizes and automatically forces fresh sessions before they hit the context ceiling. Runs on a timer (default: every 60 minutes), catches bloated sessions, deletes them, and removes their references from `sessions.json` so the gateway seamlessly creates new ones.

**The agent doesn't even notice.** It just gets a clean context window mid-conversation.

### vLLM Tool Call Proxy
A transparent proxy between OpenClaw and vLLM that post-processes responses to extract tool calls from `<tools>` tags and bare JSON, converting them to proper OpenAI `tool_calls` format. Handles both streaming (SSE) and non-streaming responses.

**Your local model subagents just start working.**

---

## Quick Start

### Linux

```bash
git clone https://github.com/Lightheartdevs/Local-Claw-Plus-Session-Manager.git
cd Local-Claw-Plus-Session-Manager

# Edit config for your setup
cp config.yaml config.yaml.bak
nano config.yaml

# Install everything
chmod +x install.sh
./install.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Lightheartdevs/Local-Claw-Plus-Session-Manager.git
cd Local-Claw-Plus-Session-Manager

# Edit config for your setup
notepad config.yaml

# Install everything
.\install.ps1
```

### Install Options

```bash
# Linux
./install.sh                      # Install everything
./install.sh --cleanup-only       # Only session cleanup (no proxy)
./install.sh --proxy-only         # Only tool proxy (no cleanup)
./install.sh --config custom.yaml # Use custom config
./install.sh --uninstall          # Remove everything

# Windows
.\install.ps1
.\install.ps1 -CleanupOnly
.\install.ps1 -ProxyOnly
.\install.ps1 -Config custom.yaml
.\install.ps1 -Uninstall
```

---

## Configuration

Edit `config.yaml` before installing:

```yaml
session_cleanup:
  enabled: true
  openclaw_dir: "~/.openclaw"
  sessions_path: "agents/main/sessions"
  max_session_size: 256000    # 250KB — tune for your model
  interval_minutes: 60        # How often to check

tool_proxy:
  enabled: true
  port: 8003
  vllm_url: "http://localhost:8000"
```

### Sizing Guide

| Model Context | Recommended max_session_size | Recommended interval |
|---|---|---|
| 8K tokens | 64000 (64KB) | 15 min |
| 16K tokens | 128000 (128KB) | 30 min |
| 32K tokens | 256000 (250KB) | 60 min |
| 64K tokens | 512000 (500KB) | 90 min |
| 128K tokens | 1024000 (1MB) | 120 min |

---

## After Installation

### Update OpenClaw Config

If you installed the tool proxy, update your `openclaw.json` model providers to route through it:

```json
{
  "models": {
    "providers": {
      "local-vllm": {
        "baseUrl": "http://localhost:8003/v1",
        "apiKey": "none",
        "api": "openai-completions"
      }
    }
  }
}
```

Change `8003` to whatever port you configured in `config.yaml`.

### Verify It's Working

```bash
# Check session cleanup timer (Linux)
systemctl status openclaw-session-cleanup.timer

# Watch cleanup logs
journalctl -u openclaw-session-cleanup -f

# Test proxy health
curl http://localhost:8003/health

# Watch proxy logs
journalctl -u vllm-tool-proxy -f
```

---

## How It Works

### Session Cleanup Flow

```
Every 60 minutes:
  1. Read sessions.json → get list of active session IDs
  2. Delete .deleted.* and .bak* debris files
  3. For each .jsonl file in sessions directory:
     - If not in active list → delete (orphan cleanup)
     - If active AND > max_session_size → delete file + remove
       reference from sessions.json (forces fresh session)
  4. Gateway detects missing session on next message → creates
     new one automatically. Agent gets clean context.
```

### Tool Proxy Flow

```
OpenClaw request with tools:
  1. Forward request to vLLM unchanged (no tool_choice forcing)
  2. Receive response (streaming or non-streaming)
  3. Check if content contains <tools>...</tools> tags or bare JSON
  4. If found: extract tool calls, convert to OpenAI tool_calls
     format, clean content field, set finish_reason=tool_calls
  5. Return fixed response to OpenClaw
  6. Subagents receive proper tool calls and execute normally
```

---

## Supported Models

The tool proxy works with any model that outputs tool calls in content instead of using the native OpenAI format:

- **Qwen2.5-Coder** (all sizes) — outputs `<tools>` tags
- **Qwen2.5 Instruct** (all sizes) — outputs `<tools>` tags
- **Models outputting bare JSON** — detected automatically
- Any future model with similar behavior

---

## Troubleshooting

### Proxy won't start — port in use
```bash
# Check what's using the port
ss -tlnp | grep 8003
# Kill the old process, then restart
sudo systemctl restart vllm-tool-proxy
```

### Cleanup not running
```bash
# Check timer status
systemctl status openclaw-session-cleanup.timer
# Run manually to test
bash ~/.openclaw/session-cleanup.sh
```

### Sessions still growing too large
Lower `max_session_size` and `interval_minutes` in `config.yaml`, then reinstall:
```bash
./install.sh  # Re-running overwrites with new config
```

### Tool calls still not working
1. Verify proxy is running: `curl http://localhost:8003/health`
2. Verify `openclaw.json` points to proxy port, not vLLM directly
3. Verify `api` is set to `openai-completions` (not `openai-responses`)
4. Check proxy logs: `journalctl -u vllm-tool-proxy -f`

---

## Project Structure

```
Local-Claw-Plus-Session-Manager/
├── config.yaml                     # Configuration file
├── install.sh                      # Linux installer
├── install.ps1                     # Windows installer
├── scripts/
│   ├── session-cleanup.sh          # Session cleanup script
│   └── vllm-tool-proxy.py         # vLLM tool call proxy
├── systemd/
│   ├── openclaw-session-cleanup.service
│   ├── openclaw-session-cleanup.timer
│   └── vllm-tool-proxy.service
├── LICENSE
└── README.md
```

---

## License

MIT License — see [LICENSE](LICENSE)

---

## Credits

Built by [Lightheart Dev Studios](https://github.com/Lightheartdevs) from real production pain running autonomous AI agents on local hardware. If this saved your agents from crashing, give us a star.
