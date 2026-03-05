#!/bin/sh
# =============================================================================
# convert.sh
# Called by memory_consolidator.py via: docker exec zim-writer /scripts/convert.sh
#
# Usage:
#   /scripts/convert.sh <staging_dir> <output_dir> <kiwix_library_dir> \
#                       <zim_name> <timestamp>
#
# Arguments:
#   staging_dir       — directory containing generated HTML articles
#   output_dir        — where zimwriterfs writes the .zim file
#   kiwix_library_dir — final destination (Kiwix library folder)
#   zim_name          — filename for the ZIM (e.g. memory-archive-2026-03.zim)
#   timestamp         — human-readable label (e.g. 2026-03)
# =============================================================================

STAGING_DIR="${1}"
OUTPUT_DIR="${2}"
KIWIX_LIBRARY_DIR="${3}"
ZIM_NAME="${4}"
TIMESTAMP="${5}"

# Validate required args
if [ -z "$STAGING_DIR" ] || [ -z "$OUTPUT_DIR" ] || \
   [ -z "$KIWIX_LIBRARY_DIR" ] || [ -z "$ZIM_NAME" ] || [ -z "$TIMESTAMP" ]; then
    echo "[convert.sh] ERROR: Missing required arguments."
    echo "Usage: convert.sh <staging_dir> <output_dir> <kiwix_lib_dir> <zim_name> <timestamp>"
    exit 1
fi

ZIM_BASE="${ZIM_NAME%.zim}"
ZIM_OUTPUT_PATH="${OUTPUT_DIR}/${ZIM_NAME}"
ZIM_FINAL_PATH="${KIWIX_LIBRARY_DIR}/${ZIM_NAME}"

echo "[convert.sh] Starting ZIM creation: ${ZIM_NAME}"
echo "[convert.sh] Source:      ${STAGING_DIR}"
echo "[convert.sh] Output:      ${ZIM_OUTPUT_PATH}"
echo "[convert.sh] Destination: ${ZIM_FINAL_PATH}"

# Ensure output dir exists
mkdir -p "${OUTPUT_DIR}"

# Run zimwriterfs
zimwriterfs \
    --welcome index.html \
    --language eng \
    --title "Memory Archive ${TIMESTAMP}" \
    --description "Consolidated session memory — technical corrections, hardware specs, constraints" \
    --creator "pcmitchum" \
    --publisher "owui-zero-vram-memory" \
    --name "${ZIM_BASE}" \
    --withFullTextIndex \
    "${STAGING_DIR}" \
    "${ZIM_OUTPUT_PATH}"

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "[convert.sh] ERROR: zimwriterfs exited with code ${EXIT_CODE}"
    exit $EXIT_CODE
fi

echo "[convert.sh] ZIM created successfully: ${ZIM_OUTPUT_PATH}"

# Move to Kiwix library
mkdir -p "${KIWIX_LIBRARY_DIR}"
mv "${ZIM_OUTPUT_PATH}" "${ZIM_FINAL_PATH}"

if [ $? -ne 0 ]; then
    echo "[convert.sh] ERROR: Failed to move ZIM to Kiwix library"
    exit 1
fi

echo "[convert.sh] ZIM archived to Kiwix library: ${ZIM_FINAL_PATH}"
echo "[convert.sh] Done. Restart kiwix-lib to detect the new ZIM."
