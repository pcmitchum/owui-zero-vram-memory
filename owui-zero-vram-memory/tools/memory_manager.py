"""
title: Persistent Memory Manager
description: Gives the model tools to save and delete entries in core_memory.txt.
             Proactively saves personal info, hardware specs, corrections, workflow
             preferences, and feedback without waiting to be asked.
             Part of the owui-zero-vram-memory stack.
author: pcmitchum
author_url: https://github.com/pcmitchum/owui-zero-vram-memory
version: 2.0.0

SETUP:
  1. Install this tool:
     Workspace → Tools → + Add → paste this file → Save

  2. Enable on your model:
     Workspace → Models → [your model] → Tools → toggle on Persistent Memory Manager

  3. No path changes needed for standard Open WebUI Docker installs.
     If your Open WebUI data directory is in a non-standard location,
     update the memory_file Valve:
     Workspace → Tools → Persistent Memory Manager → (gear icon) → Valves
"""

import os
import fcntl
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional

# Default path is correct for standard Open WebUI Docker installs.
# Change if your Open WebUI container mounts data to a different path.
MEMORY_FILE = "/app/backend/data/core_memory.txt"
MAX_ENTRIES = 200


class Tools:

    class Valves(BaseModel):
        memory_file: str = Field(
            default=MEMORY_FILE,
            description=(
                "Path to core_memory.txt inside the OpenWebUI container. "
                "Default is correct for standard Docker installs."
            )
        )
        max_entries: int = Field(
            default=MAX_ENTRIES,
            description="Maximum number of memory entries before the model is told to consolidate."
        )

    def __init__(self):
        self.valves = self.Valves()

    def save_core_memory(
        self,
        preference_or_rule: str,
        category: str = "general"
    ) -> str:
        """
        Proactively call this tool when you detect any of the following,
        WITHOUT waiting to be asked:

        - User corrects an error in your response
        - User shares personal information (name, family, location, occupation)
        - User mentions hardware or software specs (GPUs, servers, OS, Docker
          containers, apps, network addresses, IP addresses)
        - User describes a workflow, preference, or repeated pattern
        - User provides feedback on response quality or formatting
        - User mentions a technical constraint or integration requirement
        - User shares information about their homelab or self-hosted services
        - User mentions their business or professional context

        Skips saving if a near-identical entry already exists.

        :param preference_or_rule: The preference, rule, fact, or correction to save.
        :param category: One of: general, technical, workflow, persona,
                         constraint, hardware, feedback.
        """
        entry = (
            f"[{datetime.now().strftime('%Y-%m-%d')}] "
            f"[{category.upper()}] "
            f"{preference_or_rule.strip()}"
        )

        try:
            existing = []
            if os.path.exists(self.valves.memory_file):
                with open(self.valves.memory_file, "r") as f:
                    existing = f.readlines()

            core_text = preference_or_rule.strip().lower()
            for line in existing:
                if core_text in line.lower():
                    return "Memory already exists (skipped duplicate)."

            if len(existing) >= self.valves.max_entries:
                return (
                    f"Memory full ({self.valves.max_entries} entries). "
                    f"Ask the user to run consolidate_memory() to archive "
                    f"old entries to Kiwix."
                )

            with open(self.valves.memory_file, "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(f"{entry}\n")
                fcntl.flock(f, fcntl.LOCK_UN)

            return f"Saved: {entry}"

        except Exception as e:
            return f"Failed to save: {e}"

    def delete_core_memory(self, keyword: str) -> str:
        """
        Remove all memory entries containing the given keyword.
        Use when the user says to forget or update something — for example
        when hardware changes, a preference changes, or a correction is superseded.

        :param keyword: Word or phrase to match against existing memory entries.
        """
        if not os.path.exists(self.valves.memory_file):
            return "No memory file found."

        try:
            with open(self.valves.memory_file, "r") as f:
                lines = f.readlines()

            kept    = [l for l in lines if keyword.lower() not in l.lower()]
            removed = len(lines) - len(kept)

            with open(self.valves.memory_file, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.writelines(kept)
                fcntl.flock(f, fcntl.LOCK_UN)

            return (
                f"Removed {removed} "
                f"entr{'y' if removed == 1 else 'ies'} "
                f"matching '{keyword}'."
            )

        except Exception as e:
            return f"Failed to delete: {e}"
