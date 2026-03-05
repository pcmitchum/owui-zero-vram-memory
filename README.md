# owui-zero-vram-memory

**Persistent memory and automatic knowledge consolidation for Open WebUI — zero VRAM, no vector database.**

Part of a broader zero-VRAM local AI stack by [@pcmitchum](https://github.com/pcmitchum).

---

## What This Is

A self-managing, three-tier memory system for Open WebUI that gives local LLMs persistent memory across sessions without consuming VRAM, running an embedding model, or requiring a vector database.

Short-term corrections and preferences accumulate in a plain text file and are injected into every conversation automatically. When entries mature, they are automatically packaged into a ZIM file and archived to your Kiwix library — becoming permanently queryable knowledge.

```
Conversation
    ↓
core_memory.txt  ← injected into every message (zero VRAM, microsecond reads)
    ↓  [90 days or 175 entries — configurable]
memory-archive-YYYY-MM.zim  ← indexed in Kiwix, queryable on demand
```

---

## Why Zero VRAM

Standard memory and RAG solutions require an embedding model to generate and query vectors. On constrained hardware, that competes directly with your LLM for VRAM.

This stack uses:
- **Flat-file injection** — plain text prepended to system prompt, no embeddings
- **Kiwix native search** — text search via HTTP, no vector DB
- **zimwriterfs** for archival — CPU-only sidecar container

Total additional VRAM cost: **zero**.

---

## Prerequisites

- **Open WebUI** running in Docker
- **Kiwix** running in Docker on the same network as Open WebUI
  - Download ZIM files from [library.kiwix.org](https://library.kiwix.org)
  - This repo does not include a Kiwix setup — bring your own instance
- A **Kiwix search tool** installed in Open WebUI to query your ZIM library
  - The consolidation system writes memory-archive ZIMs to your existing Kiwix library
  - Any OpenWebUI Kiwix tool that can query your instance will work
- Docker socket accessible from within Open WebUI (for `docker exec` calls to zim-writer)

---

## Components

| File | Type | Purpose |
|------|------|---------|
| `filters/memory_injector.py` | OpenWebUI Filter | Injects memories into every system prompt; monitors thresholds; triggers auto-consolidation |
| `tools/memory_manager.py` | OpenWebUI Tool | Model-callable save and delete for memory entries |
| `tools/memory_consolidator.py` | OpenWebUI Tool | Model-callable manual consolidation to ZIM |
| `services/zim-writer/docker-compose.yml` | Docker Compose | zim-writer sidecar container |
| `services/zim-writer/convert.sh` | Shell script | Called by consolidator tool via docker exec |
| `services/zim-writer/auto_consolidate.sh` | Shell script | Called by cron and Filter auto-trigger |
| `services/zim-writer/crontab` | Crontab | Scheduled consolidation (configurable) |

---

## Step 1 — Find Your Paths

You need four values before touching any config file.

**OpenWebUI data path:**
```bash
docker inspect open-webui | grep -A5 '"Mounts"' | grep Source
```
This is the host folder mapped to `/app/backend/data` inside the container.

**Kiwix ZIM path:**
```bash
docker inspect <your-kiwix-container-name> | grep -A5 '"Mounts"' | grep Source
```
This is the host folder mapped to `/data` inside Kiwix — where your ZIM files live and where memory-archive ZIMs will be written.

**Docker network name:**
```bash
docker network ls
docker inspect open-webui | grep '"com.docker.compose.project"'
```
Match the project name to a network in `docker network ls`. Platform-managed stacks (TrueNAS, Portainer, etc.) often prefix network names — use the full name exactly as shown.

**Kiwix container name:**
```bash
docker ps | grep kiwix
```

---

## Step 2 — Set Up the Scripts Directory

Create a persistent directory for the zim-writer scripts on your host and copy the three files into it:

```bash
mkdir -p /your/scripts/path
cp services/zim-writer/convert.sh          /your/scripts/path/
cp services/zim-writer/auto_consolidate.sh /your/scripts/path/
cp services/zim-writer/crontab             /your/scripts/path/
chmod +x /your/scripts/path/convert.sh
chmod +x /your/scripts/path/auto_consolidate.sh
```

Then edit `crontab` and replace `<CHANGE_ME: KIWIX_ZIM_PATH>` with your actual Kiwix ZIM path:

```
# Change:
    <CHANGE_ME: KIWIX_ZIM_PATH> \
# To your path, e.g.:
    /opt/kiwix/zims \
```

---

## Step 3 — Mount the Docker Socket

The consolidator calls `docker exec` from inside Open WebUI. This requires the Docker socket to be mounted.

Add to your Open WebUI service in `docker-compose.yml`:

```yaml
volumes:
  - /your/openwebui/data:/app/backend/data
  - /var/run/docker.sock:/var/run/docker.sock   # ADD THIS
```

Apply and verify:
```bash
docker compose up -d open-webui
docker exec open-webui ls /var/run/docker.sock
# Should return: /var/run/docker.sock
```

> **Security note:** Mounting the Docker socket grants the container root-equivalent access to your Docker daemon. If this is a concern, use a socket proxy (e.g. `tecnativa/docker-socket-proxy`) restricted to exec-only operations.

> **TrueNAS / platform-managed stacks:** Use the platform UI to add the volume mount rather than editing the compose file directly, to avoid it being overwritten on app updates.

---

## Step 4 — Deploy zim-writer

Open `services/zim-writer/docker-compose.yml` and replace all `<CHANGE_ME>` values:

| Placeholder | Replace with |
|-------------|-------------|
| `NETWORK_NAME` | Your Docker network name |
| `OPENWEBUI_DATA_PATH` | Your OpenWebUI data path |
| `KIWIX_ZIM_PATH` | Your Kiwix ZIM path — appears **twice** in the volume line |
| `SCRIPTS_PATH` | The scripts directory from Step 2 |

Deploy:
```bash
docker compose -f services/zim-writer/docker-compose.yml up -d
```

Verify all four:
```bash
docker ps | grep zim-writer
docker exec zim-writer crontab -l
docker exec zim-writer zimwriterfs --version
docker exec zim-writer ls /scripts/
```

---

## Step 5 — Install the Filter

1. Open WebUI → **Workspace → Functions → + Add**
2. Paste the full contents of `filters/memory_injector.py`
3. Save
4. Click the **globe icon** to enable globally

Update Valves (gear icon on the filter):

| Valve | Set to |
|-------|--------|
| `kiwix_library_dir` | Your Kiwix ZIM path |
| `zim_writer_container` | Your zim-writer container name (default: `zim-writer`) |

> **Known issue:** The globe icon can appear enabled while `is_active` is `0` in the database. If memories are not being injected after enabling, run:
> ```bash
> docker exec open-webui python3 -c "
> import sqlite3; conn = sqlite3.connect('/app/backend/data/webui.db')
> cur = conn.cursor()
> cur.execute(\"UPDATE function SET is_active=1 WHERE id='persistent_memory_injector'\")
> conn.commit(); conn.close(); print('Fixed')"
> ```

---

## Step 6 — Install the Tools

**Memory Manager:**
Workspace → Tools → + Add → paste `tools/memory_manager.py` → Save

**Memory Consolidator:**
Workspace → Tools → + Add → paste `tools/memory_consolidator.py` → Save
Update Valves: set `kiwix_library_dir` to your Kiwix ZIM path.

---

## Step 7 — Enable Tools on Your Model

Workspace → Models → edit your model → Tools → toggle on:
- Persistent Memory Manager
- Memory Consolidator

Save.

---

## Step 8 — Verify

**Test memory save** — open a new chat:
```
Remember that I prefer CLI over GUI for all system administration tasks.
```
You should see `save_core_memory` fire in the tool call trace.

**Test memory injection** — open a **brand new chat**:
```
What do you know about my preferences?
```
The model should answer correctly without being told again.

**Test consolidation dry run:**
```
Do a dry run consolidation of my memory.
```
The model should call `consolidate_memory()` and report what would be consolidated.

---

## Memory Categories

| Category | Permanent | Description |
|----------|-----------|-------------|
| `general` | No | Miscellaneous facts |
| `technical` | No | Technical corrections, API details, config facts |
| `hardware` | No | Device specs, IP addresses, hardware inventory |
| `constraint` | No | Hard requirements, incompatibilities |
| `feedback` | No | Response quality corrections |
| `workflow` | **Yes** | How the user likes things done — never graduates to ZIM |
| `persona` | **Yes** | Personal context, communication style — never graduates to ZIM |

---

## Auto-Consolidation Triggers

| Trigger | Condition | Handler |
|---------|-----------|---------|
| `cron` | Scheduled (default: 1st of month, 3am) | crontab inside zim-writer |
| `count` | Entry count ≥ 175 | Filter inlet check on every message |
| `age` | Oldest eligible entry > 90 days | Filter inlet check on every message |

All thresholds are configurable via Valves. Manual consolidation: tell the model "consolidate memory".

After any consolidation, restart your Kiwix container to detect the new ZIM:
```bash
docker restart <your-kiwix-container-name>
```

---

## Checking Memory and Logs

```bash
# View current memory
cat /your/openwebui/data/core_memory.txt

# Count entries
grep -c '\[' /your/openwebui/data/core_memory.txt

# View consolidation logs
docker exec zim-writer cat /var/log/zim-writer.log

# List ZIM files
ls /your/kiwix/zims/
```

---

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full design rationale.

---

## License

MIT
