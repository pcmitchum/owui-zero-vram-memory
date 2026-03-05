"""
title: Memory Consolidator
description: Converts mature memory entries to a ZIM file, archives them to the
             Kiwix library, and clears them from core_memory.txt. Calls the
             zim-writer sidecar container via docker exec.
             Part of the owui-zero-vram-memory stack.
author: pcmitchum
author_url: https://github.com/pcmitchum/owui-zero-vram-memory
version: 2.0.0

SETUP:
  1. Install this tool:
     Workspace → Tools → + Add → paste this file → Save

  2. Enable on your model:
     Workspace → Models → [your model] → Tools → toggle on Memory Consolidator

  3. Update Valves to match your environment:
     Workspace → Tools → Memory Consolidator → (gear icon) → Valves

     Key Valves to set:
       kiwix_library_dir    — host path to your Kiwix ZIM folder
                              Example: /opt/kiwix/zims
       zim_writer_container — name of your zim-writer container
                              Default "zim-writer" is correct if you used
                              the provided compose files.

  REQUIREMENTS:
    - zim-writer sidecar container must be running
      (see services/zim-writer/docker-compose.yml)
    - Docker socket must be mounted into open-webui
      (see docs/setup.md Step 3)
    - open-webui and zim-writer must share a Docker network
"""

import os
import re
import fcntl
import subprocess
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Optional

MEMORY_FILE          = "/app/backend/data/core_memory.txt"
KIWIX_LIBRARY_DIR    = "/data"          # CHANGE: host path to your Kiwix ZIM folder
HTML_STAGING_DIR     = "/app/backend/data/zim_staging"
ZIM_OUTPUT_DIR       = "/app/backend/data/zim_output"
ZIM_WRITER_CONTAINER = "zim-writer"
MAX_ENTRY_AGE_DAYS   = 90

PERMANENT_CATEGORIES = {"WORKFLOW", "PERSONA"}


class Tools:

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
                "Host path to your Kiwix ZIM library. "
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
        consolidation_age_days: int = Field(
            default=MAX_ENTRY_AGE_DAYS,
            description="Minimum age in days before an entry is eligible for consolidation."
        )
        dry_run: bool = Field(
            default=False,
            description=(
                "If true, show what would be consolidated without making any changes. "
                "Set to true first to preview before running live."
            )
        )

    def __init__(self):
        self.valves = self.Valves()

    def consolidate_memory(self, category_filter: str = "all") -> str:
        """
        Call this when the user asks to consolidate, archive, or graduate memory
        to Kiwix. Also call this when memory is approaching capacity.

        Converts mature TECHNICAL, HARDWARE, GENERAL, CONSTRAINT, and FEEDBACK
        entries to a ZIM file, drops it in the Kiwix library, and removes
        consolidated entries from core_memory.txt.

        WORKFLOW and PERSONA entries are NEVER consolidated — they stay in
        memory permanently because they are behavioral, not factual.

        :param category_filter: Filter to a specific category, or 'all'.
                                Options: all, technical, hardware, general,
                                constraint, feedback.
        """
        try:
            if not os.path.exists(self.valves.memory_file):
                return "No memory file found. Nothing to consolidate."

            with open(self.valves.memory_file, "r") as f:
                all_lines = f.readlines()

            if not all_lines:
                return "Memory file is empty. Nothing to consolidate."

            eligible, permanent, too_recent, invalid = self._parse_entries(
                all_lines, category_filter
            )

            if not eligible:
                msg = "No entries eligible for consolidation."
                if too_recent:
                    msg += (
                        f" {len(too_recent)} entries are under "
                        f"{self.valves.consolidation_age_days} days old."
                    )
                if permanent:
                    msg += (
                        f" {len(permanent)} permanent WORKFLOW/PERSONA entries "
                        f"will never consolidate."
                    )
                return msg

            if self.valves.dry_run:
                preview = "\n".join([e["raw"].strip() for e in eligible])
                return (
                    f"DRY RUN — {len(eligible)} entries would be consolidated:\n\n"
                    f"{preview}"
                )

            os.makedirs(self.valves.html_staging_dir, exist_ok=True)
            os.makedirs(self.valves.zim_output_dir, exist_ok=True)

            self._generate_html(eligible)

            timestamp = datetime.now().strftime("%Y-%m")
            zim_name  = f"memory-archive-{timestamp}.zim"

            result = self._run_sidecar(zim_name, timestamp)
            if not result["success"]:
                return f"ZIM creation failed: {result['error']}"

            keep_raws = (
                {e["raw"] for e in permanent} |
                {e["raw"] for e in too_recent} |
                {e["raw"] for e in invalid}
            )
            keep_lines = [l for l in all_lines if l in keep_raws]

            with open(self.valves.memory_file, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.writelines(keep_lines)
                fcntl.flock(f, fcntl.LOCK_UN)

            import shutil
            shutil.rmtree(self.valves.html_staging_dir, ignore_errors=True)

            return (
                f"Successfully consolidated {len(eligible)} entries into "
                f"{zim_name}.\n"
                f"ZIM archived to Kiwix library at "
                f"{self.valves.kiwix_library_dir}/{zim_name}.\n"
                f"Kept {len(permanent)} permanent WORKFLOW/PERSONA entries "
                f"and {len(too_recent)} entries under "
                f"{self.valves.consolidation_age_days} days old.\n"
                f"Restart your kiwix container to detect the new ZIM."
            )

        except Exception as e:
            return f"Consolidation failed: {e}"

    def _parse_entries(self, lines, category_filter):
        eligible   = []
        permanent  = []
        too_recent = []
        invalid    = []
        cutoff     = datetime.now() - timedelta(days=self.valves.consolidation_age_days)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            match = re.match(
                r'\[(\d{4}-\d{2}-\d{2})\]\s+\[([A-Z]+)\]\s+(.*)',
                stripped
            )
            if not match:
                invalid.append({"raw": line})
                continue

            date_str, category, content = match.groups()
            entry_date = datetime.strptime(date_str, "%Y-%m-%d")

            entry = {
                "raw":      line,
                "date":     entry_date,
                "category": category,
                "content":  content,
            }

            if category in PERMANENT_CATEGORIES:
                permanent.append(entry)
            elif entry_date >= cutoff:
                too_recent.append(entry)
            elif category_filter != "all" and category.lower() != category_filter.lower():
                too_recent.append(entry)
            else:
                eligible.append(entry)

        return eligible, permanent, too_recent, invalid

    def _generate_html(self, entries):
        by_category = {}
        for entry in entries:
            by_category.setdefault(entry["category"], []).append(entry)

        cat_links = "\n".join(
            f'<li><a href="{cat.lower()}.html">'
            f'{cat.title()}</a> ({len(items)} entries)</li>'
            for cat, items in by_category.items()
        )
        index_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Memory Archive</title>
<style>
  body {{font-family: monospace; max-width: 900px; margin: 40px auto; padding: 0 20px;}}
  h1 {{border-bottom: 2px solid #333;}}
  ul {{line-height: 1.8;}}
</style>
</head><body>
<h1>Memory Archive</h1>
<p>Consolidated knowledge graduated from session memory.</p>
<ul>{cat_links}</ul>
</body></html>"""

        with open(
            os.path.join(self.valves.html_staging_dir, "index.html"), "w"
        ) as f:
            f.write(index_html)

        for cat, cat_entries in by_category.items():
            rows = "\n".join(
                f'<div class="entry">'
                f'<div class="date">{e["date"].strftime("%Y-%m-%d")}</div>'
                f'<div class="content">{e["content"]}</div>'
                f'</div>'
                for e in sorted(cat_entries, key=lambda x: x["date"])
            )
            article_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{cat.title()} — Memory Archive</title>
<style>
  body {{font-family: monospace; max-width: 900px; margin: 40px auto; padding: 0 20px;}}
  h1 {{border-bottom: 2px solid #333;}}
  .entry {{border-left: 3px solid #666; padding: 8px 16px; margin: 12px 0;}}
  .date {{color: #888; font-size: 0.85em;}}
  .content {{margin-top: 4px;}}
</style>
</head><body>
<h1>{cat.title()}</h1>
<p><a href="index.html">← Back to index</a></p>
{rows}
</body></html>"""

            with open(
                os.path.join(self.valves.html_staging_dir, f"{cat.lower()}.html"), "w"
            ) as f:
                f.write(article_html)

    def _run_sidecar(self, zim_name, timestamp):
        try:
            cmd = [
                "docker", "exec", self.valves.zim_writer_container,
                "/scripts/convert.sh",
                self.valves.html_staging_dir,
                self.valves.zim_output_dir,
                self.valves.kiwix_library_dir,
                zim_name,
                timestamp,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            return {"success": True}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "zimwriterfs timed out after 180s"}
        except FileNotFoundError:
            return {
                "success": False,
                "error": (
                    "docker command not found. Ensure the Docker socket is mounted "
                    "into the OpenWebUI container. See docs/setup.md Step 3."
                )
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
