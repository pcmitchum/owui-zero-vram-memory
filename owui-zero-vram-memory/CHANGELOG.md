# Changelog

## [2.0.0] — 2026-03-05

### Added
- `memory_consolidator.py` — model-callable Tool to manually trigger ZIM consolidation
- `services/zim-writer/` — zim-writer sidecar using `ghcr.io/openzim/zim-tools:latest`
- `services/zim-writer/convert.sh` — called by consolidator tool via docker exec
- `services/zim-writer/auto_consolidate.sh` — called by cron and Filter auto-trigger
- `services/zim-writer/crontab` — monthly schedule (1st of month, 3:00am)
- `services/zim-writer/docker-compose.yml` — sidecar deployment for TrueNAS / ai-net
- Three-tier auto-consolidation trigger system:
  - Tier 1: User-initiated via `consolidate_memory()` tool call
  - Tier 2: Filter inlet threshold check (count ≥ 175 or age ≥ 90 days)
  - Tier 3: Monthly cron inside zim-writer sidecar
- `docs/architecture.md` — full design rationale and component diagrams
- `docs/setup.md` — TrueNAS-specific deployment walkthrough
- Pydantic Valves on all components for UI-based configuration
- `dry_run` Valve on consolidator for safe previewing before committing
- WORKFLOW and PERSONA categories now explicitly protected from consolidation

### Changed
- `memory_injector.py` bumped to v2.0.0
  - Added `_check_consolidation_threshold()` called silently on every inlet
  - Added `_run_consolidation()` using non-blocking `subprocess.Popen` + docker exec
  - Added Valves for all configurable paths and thresholds
  - Injection header and instruction now configurable via Valves
- `memory_manager.py` bumped to v2.0.0
  - Added Pydantic Valves for `memory_file` and `max_entries`
  - Expanded `save_core_memory` docstring with full proactive trigger list
  - Added `hardware` and `feedback` to category list
  - "Memory full" message now directs model to call `consolidate_memory()`
- `memory_consolidator.py` replaces standalone `read_core_memory` function
  - Sidecar exec approach replaces Docker-in-Docker subprocess call

### Removed
- `read_core_memory()` function — replaced by Filter injection (always-on)

---

## [1.1.0] — 2026-03-05

### Changed
- `memory_injector.py`: Injection header updated to "READ BEFORE RESPONDING"
  with explicit instruction to check entries before formulating response
- `memory_manager.py`: Expanded `save_core_memory` docstring to trigger
  proactively on personal info, hardware specs, feedback, homelab context
- Both files: Added `hardware` and `feedback` as explicit categories

---

## [1.0.0] — 2026-03-05

### Added
- Initial release
- `memory_injector.py` — Filter with inlet/outlet, non-destructive system prompt injection
- `memory_manager.py` — Tool with `save_core_memory` and `delete_core_memory`
- Timestamped entries with category labels
- Deduplication via substring match
- File locking via `fcntl`
- Entry count cap (200)
