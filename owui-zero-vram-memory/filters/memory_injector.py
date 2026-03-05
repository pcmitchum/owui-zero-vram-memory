"""
title: Persistent Memory Injector
description: Automatically injects core_memory.txt into the system prompt on every
             message. Includes silent auto-consolidation triggers based on entry count
             and entry age. Part of the owui-zero-vram-memory stack.
author: pcmitchum
author_url: https://github.com/pcmitchum/owui-zero-vram-memory
version: 2.0.0

SETUP:
  This filter works out of the box with default paths for standard Open WebUI
  Docker deployments. If your setup differs, adjust the Valves in the UI:

  Workspace → Functions → Persistent Memory Injector → (gear icon) → Valves

  Key Valves to check:
    memory_file        — should point to core_memory.txt inside the container.
                         Default /app/backend/data/core_memory.txt is correct
                         for standard Open WebUI Docker installs.
    kiwix_library_dir  — host path to your Kiwix ZIM folder.
                         CHANGE THIS to match your KIWIX_ZIM_PATH.
    zim_writer_container — name of your zim-writer container.
                           Default "zim-writer" matches the compose files in
                           services/zim-writer/ and services/full-stack/.

  After installing, enable globally:
    Workspace → Functions → click the globe icon on this filter

  Troubleshooting — if the filter appears enabled but memories are not injecting:
    Check is_active in the database:
    docker exec open-webui python3 -c "
    import sqlite3; conn = sqlite3.connect('/app/backend/data/webui.db')
    cur = conn.cursor()
    cur.execute(\"SELECT id, is_active, is_global FROM function WHERE id='persistent_memory_injector'\")
    print(cur.fetchone()); conn.close()"

    If is_active=0, fix with:
    docker exec open-webui python3 -c "
    import sqlite3; conn = sqlite3.connect('/app/backend/data/webui.db')
    cur = conn.cursor()
    cur.execute(\"UPDATE function SET is_active=1 WHERE id='persistent_memory_injector'\")
    conn.commit(); conn.close()"
"""

import os
import re
import fcntl
import subprocess
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Optional

# ---------------------------------------------------------------------------
# Defaults — all overridable via Valves in the OpenWebUI UI.
# Standard Open WebUI Docker installs should not need to change MEMORY_FILE.
# KIWIX_LIBRARY_DIR and ZIM_WRITER_CONTAINER should match your environment.
# ---------------------------------------------------------------------------
MEMORY_FILE          = "/app/backend/data/core_memory.txt"
KIWIX_LIBRARY_DIR    = "/data"          # CHANGE: host path to your Kiwix ZIM folder
HTML_STAGING_DIR     = "/app/backend/data/zim_staging"
ZIM_OUTPUT_DIR       = "/app/backend/data/zim_output"
ZIM_WRITER_CONTAINER = "zim-writer"     # CHANGE: if your container has a different name

MAX_ENTRIES          = 200
AUTO_CONSOLIDATE_AT  = 175
MAX_ENTRY_AGE_DAYS   = 90
PERMANENT_CATEGORIES = {"WORKFLOW", "PERSONA"}


class Filter:

    class Valves(BaseModel):
        memory_file: str = Field(
            default=MEMORY_FILE,
            description=(
                "Path to core_memory.txt inside the OpenWebUI container. "
                "Default is correct for standard Docker installs."
            )
        )
        kiwix_library_dir: str = Field(
            default=KIWIX_LIBRARY_DIR,
            description=(
                "Host path to your Kiwix ZIM library folder. "
                "Must match the volume mounted into your kiwix container. "
                "Example: /opt/kiwix/zims"
            )
        )
        html_staging_dir: str = Field(
            default=HTML_STAGING_DIR,
            description="Temp directory for HTML generation before ZIM packaging."
        )
        zim_output_dir: str = Field(
            default=ZIM_OUTPUT_DIR,
            description="Directory where ZIM is written before moving to Kiwix library."
        )
        zim_writer_container: str = Field(
            default=ZIM_WRITER_CONTAINER,
            description=(
                "Name of the zim-writer sidecar container. "
                "Default 'zim-writer' matches the provided compose files."
            )
        )
        max_entries: int = Field(
            default=MAX_ENTRIES,
            description="Hard cap on memory entries before model is told to consolidate."
        )
        auto_consolidate_at: int = Field(
            default=AUTO_CONSOLIDATE_AT,
            description="Entry count that silently triggers auto-consolidation."
        )
        max_entry_age_days: int = Field(
            default=MAX_ENTRY_AGE_DAYS,
            description="Age in days before eligible entries are auto-consolidated."
        )
        injection_header: str = Field(
            default="PERSISTENT USER MEMORY - READ BEFORE RESPONDING",
            description="Header shown above injected memories in the system prompt."
        )
        injection_instruction: str = Field(
            default=(
                "The following entries contain verified corrections, technical constraints, "
                "and workflow preferences established in previous sessions. "
                "Before formulating any response, check these entries for relevant rules "
                "or corrections and apply them strictly."
            ),
            description="Instruction shown below the header, above the memory entries."
        )

    def __init__(self):
        self.valves = self.Valves()
        if not os.path.exists(self.valves.memory_file):
            with open(self.valves.memory_file, "w") as f:
                f.write("")

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])

        try:
            self._check_consolidation_threshold()
        except Exception:
            pass

        try:
            with open(self.valves.memory_file, "r") as f:
                memories = f.read().strip()
        except Exception:
            memories = ""

        if memories:
            memory_block = (
                f"\n\n[{self.valves.injection_header}]\n"
                f"{self.valves.injection_instruction}\n\n"
                f"{memories}"
            )
            if messages and messages[0]["role"] == "system":
                messages[0]["content"] += memory_block
            else:
                messages.insert(0, {"role": "system", "content": memory_block.strip()})

        body["messages"] = messages
        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        return body

    def _check_consolidation_threshold(self):
        if not os.path.exists(self.valves.memory_file):
            return

        with open(self.valves.memory_file, "r") as f:
            lines = [l for l in f.readlines() if l.strip()]

        if not lines:
            return

        if len(lines) >= self.valves.auto_consolidate_at:
            self._run_consolidation(trigger="count")
            return

        cutoff = datetime.now() - timedelta(days=self.valves.max_entry_age_days)
        for line in lines:
            match = re.match(r"\[(\d{4}-\d{2}-\d{2})\]\s+\[([A-Z]+)\]", line)
            if match:
                date_str, category = match.groups()
                if category not in PERMANENT_CATEGORIES:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if entry_date < cutoff:
                        self._run_consolidation(trigger="age")
                        return

    def _run_consolidation(self, trigger: str = "auto"):
        try:
            os.makedirs(self.valves.html_staging_dir, exist_ok=True)
            os.makedirs(self.valves.zim_output_dir, exist_ok=True)

            cmd = [
                "docker", "exec", self.valves.zim_writer_container,
                "/scripts/auto_consolidate.sh",
                self.valves.memory_file,
                self.valves.html_staging_dir,
                self.valves.zim_output_dir,
                self.valves.kiwix_library_dir,
                str(self.valves.max_entry_age_days),
                trigger,
            ]

            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            import sys
            print(
                f"[memory_injector] auto-consolidation failed ({trigger}): {e}",
                file=sys.stderr,
            )
