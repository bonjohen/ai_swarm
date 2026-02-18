# Ollama Setup — MacBook Pro M4 64 GB

Target configuration: two deepseek-r1:1.5b tiers + llama3:70b, co-resident with the claw agent.

## Memory Budget

| Component              | Estimated RAM |
|------------------------|---------------|
| macOS + system         | ~6 GB         |
| Claw agent (Python)    | ~1-2 GB       |
| deepseek-r1:1.5b       | ~1 GB         |
| llama3:70b (Q4_K_M)   | ~40 GB        |
| KV caches (8192 ctx)  | ~2-4 GB       |
| **Remaining headroom** | **~11-14 GB** |

Both tier1 (micro) and tier2 (light) share the same `deepseek-r1:1.5b` model weights in memory — Ollama loads them once. The tiers differ only in request parameters (context window, max tokens, temperature).

## 1. Install Ollama

```bash
# Download and install
curl -fsSL https://ollama.com/install.sh | sh

# Verify installation
ollama --version
```

## 2. Pull Models

```bash
# Tier 1 + Tier 2 model (tiny — takes seconds)
ollama pull deepseek-r1:1.5b

# Tier 3 frontier model (Q4_K_M — ~40 GB, takes several minutes)
ollama pull llama3:70b-instruct-q4_K_M
```

Verify both are present:

```bash
ollama list
```

Expected output should show both `deepseek-r1:1.5b` and `llama3:70b-instruct-q4_K_M`.

## 3. Configure Ollama for Concurrent Multi-Model Serving

By default Ollama keeps only one model loaded and serves one request at a time. For three tiers running concurrently, override these defaults.

Create or edit `~/.ollama/env` (or set as environment variables before starting):

```bash
cat > ~/.ollama/env << 'EOF'
# Keep both models loaded simultaneously (deepseek-r1:1.5b + llama3:70b)
OLLAMA_MAX_LOADED_MODELS=2

# Allow up to 4 concurrent requests per model
OLLAMA_NUM_PARALLEL=4

# Listen on all interfaces (needed if claw agent runs on another machine)
# For local-only access, leave this unset or use 127.0.0.1
OLLAMA_HOST=0.0.0.0

# Pin GPU layers — let Ollama use all available Metal cores
OLLAMA_NUM_GPU=999
EOF
```

Restart Ollama to pick up changes:

```bash
# If running as a service (default on macOS after install)
brew services restart ollama

# Or if running manually
pkill ollama && ollama serve
```

## 4. Validate Models Load and Run

```bash
# Quick smoke test — tier1/tier2 model
ollama run deepseek-r1:1.5b "Respond with only: OK"

# Quick smoke test — tier3 model (first run loads into memory, may take 10-20s)
ollama run llama3:70b-instruct-q4_K_M "Respond with only: OK"
```

Verify both are loaded simultaneously:

```bash
curl -s http://localhost:11434/api/ps | python3 -m json.tool
```

Should show two models with `size_vram` values.

## 5. Create Custom Modelfile for llama3 (Optional)

For baked-in defaults (avoids passing options on every request):

```bash
ollama create llama3-swarm -f - << 'MODELFILE'
FROM llama3:70b-instruct-q4_K_M
PARAMETER num_ctx 8192
PARAMETER temperature 0.2
PARAMETER num_gpu 999
MODELFILE
```

Then reference as `llama3-swarm` in config instead of the full tag.

## 6. Verify API Endpoints

```bash
# List all models
curl -s http://localhost:11434/api/tags | python3 -m json.tool

# Models currently loaded in memory
curl -s http://localhost:11434/api/ps | python3 -m json.tool

# Test a chat completion (same endpoint our adapters use)
curl -s http://localhost:11434/api/chat -d '{
  "model": "deepseek-r1:1.5b",
  "messages": [{"role": "user", "content": "Say hello"}],
  "stream": false
}' | python3 -m json.tool
```

## 7. Router Config

Update `config/router_config.yaml` to point at this machine. If running the claw agent on the same MacBook, `localhost` is correct (already the default). If running remotely, replace with the MacBook's hostname or IP.

The tier1 and tier2 sections already reference `deepseek-r1:1.5b` and need no changes. Update the DGX Spark entry or add a separate local-mac entry for llama3:

```yaml
tier3_providers:
  - name: local_mac
    provider_type: ollama
    model: "llama3:70b-instruct-q4_K_M"
    host: "http://localhost:11434"
    cost_per_1k_input: 0.0
    cost_per_1k_output: 0.0
    quality_score: 0.85
    max_context: 8192
    tags: [local, frontier]
```

## Troubleshooting

**Model won't load / killed by OOM:**
```bash
# Check how much memory is available
vm_stat | head -5
# If tight, close memory-heavy apps or drop to Q3_K_M (~35 GB)
ollama pull llama3:70b-instruct-q3_K_M
```

**Ollama not listening on network:**
```bash
# Confirm binding
lsof -i :11434
# Should show ollama listening on 0.0.0.0:11434 or *:11434
```

**Slow first inference:**
Normal — first request after model load compiles Metal kernels. Subsequent requests are fast. Keep models loaded with `OLLAMA_MAX_LOADED_MODELS=2` to avoid reload latency.

**Check Ollama logs:**
```bash
cat ~/.ollama/logs/server.log | tail -50
```
