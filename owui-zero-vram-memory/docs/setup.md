# Setup Guide

Extended notes to accompany the README installation steps.

---

## Before You Start — Gather Your Paths

Everything in this stack is path-driven. Before touching any config file, run
these four commands and write down the results.

### OpenWebUI data path
```bash
docker inspect open-webui | grep -A5 '"Mounts"' | grep Source
```
Example output: `/opt/openwebui/data`
Maps to `/app/backend/data` inside the container. The default paths in all
three Python files are correct for any standard Open WebUI Docker install.

### Kiwix ZIM path
```bash
docker inspect <kiwix-container-name> | grep -A5 '"Mounts"' | grep Source
```
Example output: `/opt/kiwix/zims`
This is where your ZIM files live and where memory-archive ZIMs will be written
after consolidation. Must be the same path mounted into your Kiwix container.

### Docker network name
```bash
docker network ls
docker inspect open-webui | grep '"com.docker.compose.project"'
```
Match the project name to a network in `docker network ls`.

Platform-managed stacks (TrueNAS Scale, Portainer, Dockge, etc.) often
prefix network names. For example, a TrueNAS app named `ollama` with a network
named `ai-net` will appear as `ix-ollama_ai-net`. Use the full prefixed name
exactly as shown in `docker network ls`.

### Kiwix container name
```bash
docker ps | grep kiwix
```
The name is in the last column.

---

## Step 3 — Mount the Docker Socket

### Standard Docker Compose

Add to your `open-webui` service volumes:
```yaml
- /var/run/docker.sock:/var/run/docker.sock
```

Apply:
```bash
docker compose up -d open-webui
```

Verify:
```bash
docker exec open-webui ls /var/run/docker.sock
# Expected: /var/run/docker.sock
```

### TrueNAS Scale / Platform-Managed Apps

If your stack is managed by a platform, editing the compose file directly
may be overwritten on app updates. Use the platform UI to add the volume:

- **TrueNAS Scale:** Apps → your app → Edit → find the open-webui storage
  section → add host path `/var/run/docker.sock` mounted to `/var/run/docker.sock`

### Security Note

Mounting the Docker socket grants the container root-equivalent access to
your Docker daemon. This is required for `docker exec` calls to the
zim-writer sidecar.

To restrict access, use a Docker socket proxy:
```yaml
  socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    environment:
      EXEC: 1
      CONTAINERS: 1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - ai-net

  open-webui:
    environment:
      DOCKER_HOST: tcp://socket-proxy:2375
```

---

## Step 4 — Deploy zim-writer

### Fill in docker-compose.yml

Open `services/zim-writer/docker-compose.yml`. Every `<CHANGE_ME>` must be replaced.

```yaml
# Before:
    name: <CHANGE_ME: NETWORK_NAME>
    - <CHANGE_ME: OPENWEBUI_DATA_PATH>:/app/backend/data
    - <CHANGE_ME: KIWIX_ZIM_PATH>:<CHANGE_ME: KIWIX_ZIM_PATH>
    - <CHANGE_ME: SCRIPTS_PATH>:/scripts

# After example:
    name: ai-net
    - /opt/openwebui/data:/app/backend/data
    - /opt/kiwix/zims:/opt/kiwix/zims
    - /opt/zim-writer/scripts:/scripts
```

`KIWIX_ZIM_PATH` appears **twice** in the volume line. Both the host path and
container path must match — this is how the script writes ZIMs directly to
the location Kiwix reads from.

### Deploy
```bash
docker compose -f services/zim-writer/docker-compose.yml up -d
```

### Verify all four checks pass
```bash
docker ps | grep zim-writer
docker exec zim-writer crontab -l
docker exec zim-writer zimwriterfs --version
docker exec zim-writer ls /scripts/
```

Expected output from `ls /scripts/`:
```
auto_consolidate.sh  convert.sh  crontab
```

---

## Step 5 — Filter Known Issue

The Open WebUI globe icon (global enable) can show as active while `is_active`
is `0` in the underlying SQLite database. This happens most often after
editing and saving a function. If memories are not being injected, run:

```bash
# Check current state
docker exec open-webui python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()
cur.execute(\"SELECT id, is_active, is_global FROM function WHERE id='persistent_memory_injector'\")
print(cur.fetchone())
conn.close()"

# Expected: ('persistent_memory_injector', 1, 1)
# If is_active shows 0, fix with:

docker exec open-webui python3 -c "
import sqlite3
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()
cur.execute(\"UPDATE function SET is_active=1 WHERE id='persistent_memory_injector'\")
conn.commit()
conn.close()
print('Fixed')"
```

---

## Troubleshooting

**`save_core_memory` is not firing automatically**
- Confirm the tool is enabled on your model: Workspace → Models → [model] → Tools
- Test manually: "Use the memory tool to save that I like dark mode"
- Check Open WebUI logs: `docker logs open-webui --tail 50`

**Filter is not injecting memories**
- Run the `is_active` check above
- Confirm `core_memory.txt` exists and has content:
  `cat /your/openwebui/data/core_memory.txt`

**`docker exec` fails from consolidator**
- Confirm socket is mounted: `docker exec open-webui ls /var/run/docker.sock`
- Confirm zim-writer is running: `docker ps | grep zim-writer`
- Confirm the container name matches the `zim_writer_container` Valve value

**zimwriterfs fails during consolidation**
- Check sidecar logs: `docker logs zim-writer`
- Check consolidation logs: `docker exec zim-writer cat /var/log/zim-writer.log`
- Verify staging dir is writable inside the container:
  `docker exec zim-writer ls /app/backend/data/`

**New ZIM not appearing in Kiwix**
- Restart your Kiwix container: `docker restart <kiwix-container-name>`
- Verify the ZIM was written: `ls /your/kiwix/zims/ | grep memory-archive`
- Check file permissions on the new ZIM file

**Network not found when deploying zim-writer**
- Run `docker network ls` to see exact network names
- Platform-managed stacks often prefix names (e.g. `ix-ollama_ai-net`)
- Update the `name:` field in `services/zim-writer/docker-compose.yml` to match exactly
