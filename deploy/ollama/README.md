# Local Ollama profile: RTX 4060, 8 GiB VRAM

The starting profile uses `qwen3:4b`, 4096 context tokens, one parallel model request and one loaded model. The goal is approximately half of the GPU memory while leaving headroom for the desktop. This is not an enforced 4 GiB cap: model buffers, cache, Ollama version and other applications affect actual usage. GPU compute utilization may still reach 100% during inference.

## Project configuration

Set these in the project `.env`, reload it and restart the MCP process:

```dotenv
OLLAMA_MODEL=qwen3:4b
OLLAMA_CONTEXT_LENGTH=4096
```

The application passes the configured context explicitly as `num_ctx` and already limits model generation to one concurrent request per application process. The Ollama service settings below apply across application processes/other clients. Merely adding those service variables to the project's `.env` does not configure an already-running Ollama service.

## Ollama managed by systemd

After installing Ollama, run from the repository root:

```bash
sudo install -d -m 0755 /etc/systemd/system/ollama.service.d
sudo install -m 0644 deploy/ollama/rtx4060.conf /etc/systemd/system/ollama.service.d/linux-mcp-profile.conf
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama pull qwen3:4b
```

This restarts the local model service and interrupts its current work. It does not delete models.

## Manual Ollama process

If not using systemd, start a single Ollama server in its own terminal:

```bash
OLLAMA_HOST=127.0.0.1:11434 \
OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 \
OLLAMA_CONTEXT_LENGTH=4096 \
ollama serve
```

Do not start another process if a service already owns port 11434.

## Verify under actual chat load

```bash
ollama ps
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
```

Record GPU usage before loading a model, after loading, and during several multi-step chat turns. `nvidia-smi` reports total GPU use, including the desktop. Check `ollama ps` for GPU/CPU placement and active context size. If memory use exceeds the target or tool selection suffers, compare a shorter context (minimum 2048 in this project), shorter conversations and a smaller tool-capable model. Do not claim the memory target is met until measured on the user's host.

To remove this specific profile, delete `/etc/systemd/system/ollama.service.d/linux-mcp-profile.conf`, reload systemd and restart Ollama. Other service overrides remain separate.
