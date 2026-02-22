# Lighthouse AI

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/Light-Heart-Labs/Lighthouse-AI)](https://github.com/Light-Heart-Labs/Lighthouse-AI)

**Local AI infrastructure. Your hardware. Your data. Your rules.**

Lighthouse AI is a growing collection of tools and systems for running AI entirely on your own hardware. The flagship product is **Dream Server** — a turnkey local AI stack that goes from bare metal to running in 10 minutes. Alongside it, the **Operations Toolkit** provides battle-tested components for persistent agent management, process monitoring, API cost tracking, and more.

Everything here is open source (Apache 2.0), runs offline, and works together or independently. Grab what you need.

---

## Dream Server — Local AI in 10 Minutes

One installer. Auto-detects your GPU. Picks the right model. Generates secure passwords. Starts everything.

```bash
curl -fsSL https://raw.githubusercontent.com/Light-Heart-Labs/Lighthouse-AI/main/dream-server/get-dream-server.sh | bash
```

Or manually:

```bash
git clone https://github.com/Light-Heart-Labs/Lighthouse-AI.git
cd Lighthouse-AI/dream-server
./install.sh
```

Open **http://localhost:3000** and start chatting.

### What's Included

| Component | Purpose | Port |
|-----------|---------|------|
| **vLLM** | High-performance LLM inference (GPU-accelerated) | 8000 |
| **Open WebUI** | Chat interface with model management | 3000 |
| **Dashboard** | System status, GPU metrics, service health | 3001 |
| **Whisper** | Speech-to-text (optional) | 9000 |
| **Kokoro** | Text-to-speech (optional) | 8880 |
| **LiveKit** | Real-time WebRTC voice chat (optional) | 7880 |
| **n8n** | Workflow automation — 400+ integrations (optional) | 5678 |
| **Qdrant** | Vector database for RAG (optional) | 6333 |
| **LiteLLM** | Multi-model API gateway (optional) | 4000 |
| **Privacy Shield** | PII redaction for external API calls | 8085 |

### Hardware Tiers (Auto-Detected)

| Tier | VRAM | Model | Context | Example GPUs |
|------|------|-------|---------|--------------|
| 1 (Entry) | <12GB | Qwen2.5-7B | 8K | RTX 3080, RTX 4070 |
| 2 (Prosumer) | 12-20GB | Qwen2.5-14B-AWQ | 16K | RTX 3090, RTX 4080 |
| 3 (Pro) | 20-40GB | Qwen2.5-32B-AWQ | 32K | RTX 4090, A6000 |
| 4 (Enterprise) | 40GB+ | Qwen2.5-72B-AWQ | 32K | A100, H100, multi-GPU |

### Bootstrap Mode

Don't wait for a 20GB download. Dream Server starts instantly with a tiny 1.5B model, lets you chat within 2 minutes, then hot-swaps to the full model when it's ready:

```bash
./scripts/upgrade-model.sh   # Hot-swap to full model (zero downtime)
```

Skip bootstrap: `./install.sh --no-bootstrap`

**Full documentation:** [dream-server/README.md](dream-server/README.md) | [QUICKSTART.md](dream-server/QUICKSTART.md) | [FAQ](dream-server/FAQ.md)

---

## OpenClaw — Multi-Agent AI on Your GPU

Dream Server ships with local [OpenClaw](https://openclaw.io) support out of the box. OpenClaw is a multi-agent framework that lets AI agents coordinate autonomously on shared projects using local hardware.

**What you get:**
- **vLLM Tool Call Proxy** — Makes local model tool calling work transparently between OpenClaw and vLLM. Handles SSE re-wrapping, tool call extraction, and loop protection.
- **Golden Configs** — Battle-tested `openclaw.json` and `models.json` with the critical `compat` block that prevents silent failures.
- **Workspace Templates** — Agent personality, identity, tools, and working memory starter files.

The vLLM Tool Proxy (`scripts/vllm-tool-proxy.py`) is the bridge that makes local inference and OpenClaw agents work together. Without it, tool calls from local models get lost in translation.

**This repo is where it all started.** The [OpenClaw Collective](COLLECTIVE.md) — 3 AI agents, 3,464 commits, 8 days — produced three shipping products coordinating autonomously on local GPU hardware. These tools kept them running. Dream Server packages the result into something anyone can set up.

**Setup:** [docs/SETUP.md](docs/SETUP.md) | **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | **Patterns:** [docs/PATTERNS.md](docs/PATTERNS.md)

---

## Operations Toolkit

Standalone tools for running persistent AI agents in production. Each works independently — grab what you need.

| Component | What It Does | Requires OpenClaw? |
|-----------|-------------|-------------------|
| [**Guardian**](guardian/README.md) | Self-healing process watchdog with backup restore. Monitors processes, systemd services, Docker containers, file integrity. Runs as root — agents can't kill it. | No |
| [**Memory Shepherd**](memory-shepherd/README.md) | Periodic memory reset for persistent agents. Archives scratch notes and restores MEMORY.md to a curated baseline. Prevents identity drift. | No |
| [**Token Spy**](token-spy/README.md) | Transparent API proxy that tracks per-turn token usage, cost, latency, and session health. Real-time dashboard. Auto-kill for runaway sessions. | No |
| [**Session Watchdog**](scripts/session-cleanup.sh) | Auto-cleans bloated OpenClaw sessions before context overflow. Agent doesn't notice. | Yes |
| [**vLLM Tool Call Proxy**](scripts/vllm-tool-proxy.py) | Makes local model tool calling work with OpenClaw. Handles SSE, tool extraction, loop protection. | Yes |
| [**LLM Cold Storage**](scripts/llm-cold-storage.sh) | Archives idle HuggingFace models to free disk space. Models stay resolvable via symlink. | No |
| [**Docker Compose Stacks**](compose/) | One-command deployment: Pro tier (GPU) or Nano tier (CPU-only). | No |
| [**Golden Configs**](configs/) | Working config templates for OpenClaw + vLLM with the compat block. | Yes |
| [**Workspace Templates**](workspace/) | Agent personality/identity starter files (SOUL, IDENTITY, TOOLS, MEMORY). | Yes |

### Quick Install (Toolkit)

```bash
git clone https://github.com/Light-Heart-Labs/Lighthouse-AI.git
cd Lighthouse-AI

# Edit config for your setup
nano config.yaml

# Install everything (or pick components)
./install.sh
./install.sh --cleanup-only     # Session cleanup only
./install.sh --proxy-only       # Tool proxy only
./install.sh --token-spy-only   # Token Spy only
```

---

## Documentation

### Dream Server
- [README](dream-server/README.md) — Overview, architecture, profiles
- [QUICKSTART](dream-server/QUICKSTART.md) — Step-by-step setup guide
- [FAQ](dream-server/FAQ.md) — Troubleshooting, usage, advanced config
- [Hardware Guide](dream-server/docs/HARDWARE-GUIDE.md) — What to buy
- [Security](dream-server/SECURITY.md) — Security best practices

### Operations Toolkit
- [PHILOSOPHY](docs/PHILOSOPHY.md) — **Start here.** Five pillars of persistent agents, failure taxonomy, reading map
- [ARCHITECTURE](docs/ARCHITECTURE.md) — How it all fits together
- [SETUP](docs/SETUP.md) — Full local setup walkthrough
- [OPERATIONAL-LESSONS](docs/OPERATIONAL-LESSONS.md) — Hard-won lessons from 24/7 agent operations
- [MULTI-AGENT-PATTERNS](docs/MULTI-AGENT-PATTERNS.md) — Coordination, reliability, swarms

### Cookbook (Step-by-Step Recipes)
- [Voice Agent Setup](docs/cookbook/01-voice-agent-setup.md) — Whisper + vLLM + Kokoro
- [Document Q&A](docs/cookbook/02-document-qa-setup.md) — RAG with Qdrant/ChromaDB
- [Code Assistant](docs/cookbook/03-code-assistant-setup.md) — Tool-calling code agent
- [Privacy Proxy](docs/cookbook/04-privacy-proxy-setup.md) — PII-stripping API proxy
- [Multi-GPU Cluster](docs/cookbook/05-multi-gpu-cluster.md) — Multi-node load balancing
- [Swarm Patterns](docs/cookbook/06-swarm-patterns.md) — Sub-agent parallelization
- [n8n + Local LLM](docs/cookbook/08-n8n-local-llm.md) — Workflow automation

### Research
- [Hardware Guide](docs/research/HARDWARE-GUIDE.md) — GPU buying guide with real prices
- [GPU TTS Benchmark](docs/research/GPU-TTS-BENCHMARK.md) — TTS latency benchmarks
- [OSS Model Landscape](docs/research/OSS-MODEL-LANDSCAPE-2026-02.md) — Open-source model comparison

### Origin Story
- [COLLECTIVE.md](COLLECTIVE.md) — The multi-agent system that built these tools

---

## Project Structure

```
Lighthouse-AI/
├── dream-server/              # Turnkey local AI stack (flagship)
│   ├── install.sh             #   One-shot bare-metal installer
│   ├── docker-compose*.yml    #   Service orchestration
│   ├── dashboard/             #   React status dashboard
│   ├── dashboard-api/         #   System status API
│   ├── agents/                #   Voice and LiveKit agents
│   ├── scripts/               #   Utilities, preflight, showcase
│   ├── workflows/             #   Pre-built n8n workflows
│   ├── docs/                  #   Dream Server documentation
│   └── tests/                 #   Integration and validation tests
├── guardian/                   # Self-healing process watchdog
├── memory-shepherd/            # Periodic memory reset for agents
├── token-spy/                  # API cost & usage monitor
├── scripts/                    # Toolkit scripts (proxy, cleanup, cold storage)
├── configs/                    # Golden configs (OpenClaw + vLLM)
├── workspace/                  # Agent identity templates
├── compose/                    # Docker Compose stacks (pro/nano)
├── systemd/                    # systemd service/timer units
├── docs/                       # Toolkit documentation & cookbook
├── config.yaml                 # Toolkit configuration
├── install.sh                  # Toolkit installer
├── COLLECTIVE.md               # Origin story
└── LICENSE                     # Apache 2.0
```

---

## Contributing

Contributions welcome. Open an issue or submit a PR.

If you're building something with Dream Server or the toolkit, we'd love to hear about it.

## License

Apache 2.0 — see [LICENSE](LICENSE). Use it, modify it, ship it.

---

Built by [Lightheart Labs](https://github.com/Light-Heart-Labs) and the [Android Collective](COLLECTIVE.md).
