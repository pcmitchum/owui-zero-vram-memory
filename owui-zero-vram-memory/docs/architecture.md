# Architecture

## The Three-Layer Stack

```
┌─────────────────────────────────────────────────┐
│                  CONVERSATION                   │
└────────────────────────┬────────────────────────┘
                         │
          ┌──────────────▼──────────────┐
          │     LAYER 1: BASE MODEL     │
          │  Reasoning, language, CoT  │
          └──────────────┬──────────────┘
                         │
          ┌──────────────▼──────────────┐
          │   LAYER 2: SHORT-TERM       │
          │      core_memory.txt        │
          │  Injected every message     │
          │  Corrections, prefs, specs  │
          └──────────────┬──────────────┘
                         │  [90 days / 175 entries]
          ┌──────────────▼──────────────┐
          │   LAYER 3: LONG-TERM        │
          │   Kiwix ZIM library         │
          │  Queried on demand          │
          │  Permanent indexed archive  │
          └─────────────────────────────┘
```

The model is the inference engine. The knowledge layers are the persistent asset.
Swap the model at any time — memory and knowledge survive unchanged.

---

## Why Not Vector RAG

Standard RAG pipelines:

```
Document → Chunk → Embed → Vector DB → Semantic Search → Context injection
```

Each step costs:
- An embedding model loaded in memory (300MB–1.3GB RAM, or VRAM)
- CPU/GPU time per query to generate query embeddings
- A database process running continuously
- Cold-start latency on first query

For technical documentation and factual corrections — the primary use cases here —
semantic similarity search adds little value over text search. You're looking for
`rest_command`, not _something conceptually similar to rest_command_.

This stack replaces the entire pipeline with:

```
Kiwix native search API → HTML fetch → Context injection
```

Zero embedding overhead. Near-instant retrieval. Same quality results for
structured technical content.

---

## Memory File Format

Each entry in `core_memory.txt` follows this structure:

```
[YYYY-MM-DD] [CATEGORY] content
```

Example:
```
[2026-03-04] [TECHNICAL] Home Assistant does not have a built-in tts.http platform. Use rest_command for custom HTTP TTS integrations.
[2026-03-04] [HARDWARE] TrueNAS host: Intel i7-6700, RTX 1660 Super 6GB VRAM, 32GB DDR4
[2026-03-04] [WORKFLOW] For Home Assistant automations, always provide YAML with sunset/sunrise triggers, failure notifications, and entity ID notes.
[2026-03-04] [PERSONA] User prefers CLI over GUI for all system administration tasks.
```

---

## Consolidation Pipeline

```
core_memory.txt
      │
      │  [threshold crossed: count ≥ 175, age ≥ 90 days, or user command]
      ▼
auto_consolidate.sh  (runs inside zim-writer sidecar)
      │
      ├─ Parse eligible entries (non-WORKFLOW, non-PERSONA, over age threshold)
      ├─ Generate HTML articles grouped by category
      ├─ Run zimwriterfs to package HTML → .zim
      ├─ Move .zim to /mnt/NAS/NAS/ZIMS (Kiwix library)
      └─ Remove consolidated entries from core_memory.txt
            │
            ▼
      kiwix-lib container
      (restart to detect new ZIM)
            │
            ▼
      Kiwix tool queries new ZIM on demand
```

---

## Trigger Hierarchy

```
Tier 1 (User-initiated)
  User: "consolidate memory"
  → Model calls consolidate_memory() tool
  → Calls convert.sh in zim-writer sidecar via docker exec

Tier 2 (Filter-initiated, threshold-based)
  Every inlet: entry count checked, oldest entry age checked
  → If count ≥ 175 OR oldest eligible entry > 90 days
  → Non-blocking Popen → docker exec zim-writer auto_consolidate.sh
  → Message proceeds without waiting for consolidation to complete

Tier 3 (Cron-initiated, time-based)
  1st of every month at 3:00am
  → crond inside zim-writer fires auto_consolidate.sh directly
  → Completely independent of Open WebUI, model, and user activity
```

---

## Category Lifecycle

```
TECHNICAL   ──────────────────────────► ZIM after 90 days
HARDWARE    ──────────────────────────► ZIM after 90 days
GENERAL     ──────────────────────────► ZIM after 90 days
CONSTRAINT  ──────────────────────────► ZIM after 90 days
FEEDBACK    ──────────────────────────► ZIM after 90 days

WORKFLOW    ──────────────────────────► Permanent in memory (never graduates)
PERSONA     ──────────────────────────► Permanent in memory (never graduates)
```

WORKFLOW and PERSONA entries are behavioral — they define how the model should
interact with this user. Factual entries graduate to searchable long-term knowledge.

---

## Model Agnosticism

Every component is model-agnostic by design:

- `core_memory.txt` — plain text, any model reads it
- Kiwix ZIM files — HTTP search API, any model queries it
- Filter injection — system prompt prepend, works on any OpenWebUI model
- Tool docstrings — natural language instructions, model-independent

Upgrading from a 4B to a 14B model, or switching from Qwen to DeepSeek,
requires no changes to the memory or knowledge layer. The new model inherits
all accumulated corrections from day one.

---

## Performance Characteristics

| Operation | Cost | Notes |
|-----------|------|-------|
| Memory injection (inlet) | ~1ms | File read + string prepend |
| Threshold check (inlet) | ~1ms | Line count + regex scan |
| Kiwix text search | ~50ms | HTTP call to local container |
| ZIM consolidation | 5–30s | CPU-only, runs non-blocking |
| Monthly cron | 5–30s | Runs at 3am, no user impact |

VRAM consumed by this stack: **0 MB**
