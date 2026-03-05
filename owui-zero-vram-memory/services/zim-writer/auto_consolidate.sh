#!/bin/sh
# =============================================================================
# auto_consolidate.sh
#
# Called two ways:
#   1. By cron inside zim-writer sidecar (on your configured schedule)
#   2. By memory_injector.py Filter via docker exec when thresholds are crossed
#
# NO CHANGES NEEDED IN THIS FILE.
# All paths are passed as arguments from the caller (crontab or Filter).
#
# Usage:
#   /scripts/auto_consolidate.sh <memory_file> <staging_dir> <output_dir> \
#                                <kiwix_library_dir> <max_age_days> <trigger>
# =============================================================================

MEMORY_FILE="${1:-/app/backend/data/core_memory.txt}"
STAGING_DIR="${2:-/app/backend/data/zim_staging}"
OUTPUT_DIR="${3:-/app/backend/data/zim_output}"
KIWIX_LIBRARY_DIR="${4:-/data}"
MAX_AGE_DAYS="${5:-90}"
TRIGGER="${6:-auto}"

TIMESTAMP="$(date +%Y-%m)"
ZIM_NAME="memory-archive-${TIMESTAMP}.zim"
LOG_PREFIX="[auto_consolidate.sh | trigger=${TRIGGER}]"

echo "${LOG_PREFIX} Starting. Timestamp: ${TIMESTAMP}"

if [ ! -f "${MEMORY_FILE}" ]; then
    echo "${LOG_PREFIX} Memory file not found: ${MEMORY_FILE}. Exiting."
    exit 0
fi

ENTRY_COUNT=$(grep -c '\[' "${MEMORY_FILE}" 2>/dev/null || echo 0)
if [ "${ENTRY_COUNT}" -eq 0 ]; then
    echo "${LOG_PREFIX} Memory file is empty. Nothing to do."
    exit 0
fi

echo "${LOG_PREFIX} Found ${ENTRY_COUNT} entries. Checking eligibility..."

CUTOFF_EPOCH=$(date -d "-${MAX_AGE_DAYS} days" +%s 2>/dev/null || \
               date -v-${MAX_AGE_DAYS}d +%s 2>/dev/null)

mkdir -p "${STAGING_DIR}"
mkdir -p "${OUTPUT_DIR}"

ELIGIBLE_COUNT=0
CATEGORIES=""

while IFS= read -r line; do
    DATE=$(echo "$line" | sed -n 's/^\[\([0-9-]*\)\].*/\1/p')
    CATEGORY=$(echo "$line" | sed -n 's/^\[[0-9-]*\] \[\([A-Z]*\)\].*/\1/p')
    CONTENT=$(echo "$line" | sed -n 's/^\[[0-9-]*\] \[[A-Z]*\] //p')

    [ -z "$DATE" ] || [ -z "$CATEGORY" ] || [ -z "$CONTENT" ] && continue
    [ "$CATEGORY" = "WORKFLOW" ] || [ "$CATEGORY" = "PERSONA" ] && continue

    ENTRY_EPOCH=$(date -d "${DATE}" +%s 2>/dev/null || \
                  date -j -f "%Y-%m-%d" "${DATE}" +%s 2>/dev/null)
    [ -z "$ENTRY_EPOCH" ] && continue
    [ "$ENTRY_EPOCH" -ge "$CUTOFF_EPOCH" ] && continue

    echo "${DATE}|${CONTENT}" >> "${STAGING_DIR}/${CATEGORY}.dat"
    ELIGIBLE_COUNT=$((ELIGIBLE_COUNT + 1))
    echo "$CATEGORIES" | grep -q "$CATEGORY" || CATEGORIES="${CATEGORIES} ${CATEGORY}"

done < "${MEMORY_FILE}"

if [ "${ELIGIBLE_COUNT}" -eq 0 ]; then
    echo "${LOG_PREFIX} No entries old enough to consolidate (threshold: ${MAX_AGE_DAYS} days)."
    rm -rf "${STAGING_DIR}"
    exit 0
fi

echo "${LOG_PREFIX} ${ELIGIBLE_COUNT} eligible entries across categories:${CATEGORIES}"

CAT_LINKS=""
for CAT in ${CATEGORIES}; do
    COUNT=$(wc -l < "${STAGING_DIR}/${CAT}.dat" 2>/dev/null || echo 0)
    CAT_LINKS="${CAT_LINKS}<li><a href=\"${CAT}.html\">${CAT}</a> (${COUNT} entries)</li>\n"
done

cat > "${STAGING_DIR}/index.html" <<EOF
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Memory Archive ${TIMESTAMP}</title>
<style>
  body {font-family: monospace; max-width: 900px; margin: 40px auto; padding: 0 20px;}
  h1 {border-bottom: 2px solid #333;}
  ul {line-height: 1.8;}
</style>
</head><body>
<h1>Memory Archive ${TIMESTAMP}</h1>
<p>Auto-consolidated from session memory. Trigger: ${TRIGGER}</p>
<ul>
$(printf "%b" "${CAT_LINKS}")
</ul>
</body></html>
EOF

for CAT in ${CATEGORIES}; do
    DAT_FILE="${STAGING_DIR}/${CAT}.dat"
    [ ! -f "${DAT_FILE}" ] && continue

    {
        cat <<HEADER
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>${CAT} — Memory Archive ${TIMESTAMP}</title>
<style>
  body {font-family: monospace; max-width: 900px; margin: 40px auto; padding: 0 20px;}
  h1 {border-bottom: 2px solid #333;}
  .entry {border-left: 3px solid #666; padding: 8px 16px; margin: 12px 0;}
  .date {color: #888; font-size: 0.85em;}
  .content {margin-top: 4px;}
</style>
</head><body>
<h1>${CAT}</h1>
<p><a href="index.html">&larr; Back to index</a></p>
HEADER
        while IFS='|' read -r DATE CONTENT; do
            printf '<div class="entry"><div class="date">%s</div><div class="content">%s</div></div>\n' \
                "${DATE}" "${CONTENT}"
        done < "${DAT_FILE}"
        echo "</body></html>"
    } > "${STAGING_DIR}/${CAT}.html"

    rm "${DAT_FILE}"
done

echo "${LOG_PREFIX} Running zimwriterfs..."

zimwriterfs \
    --welcome index.html \
    --language eng \
    --title "Memory Archive ${TIMESTAMP}" \
    --description "Auto-consolidated session memory — trigger: ${TRIGGER}" \
    --creator "owui-zero-vram-memory" \
    --publisher "owui-zero-vram-memory" \
    --name "memory-archive-${TIMESTAMP}" \
    --withFullTextIndex \
    "${STAGING_DIR}" \
    "${OUTPUT_DIR}/${ZIM_NAME}"

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "${LOG_PREFIX} ERROR: zimwriterfs failed with exit code ${EXIT_CODE}"
    rm -rf "${STAGING_DIR}"
    exit $EXIT_CODE
fi

mkdir -p "${KIWIX_LIBRARY_DIR}"
mv "${OUTPUT_DIR}/${ZIM_NAME}" "${KIWIX_LIBRARY_DIR}/${ZIM_NAME}"

if [ $? -ne 0 ]; then
    echo "${LOG_PREFIX} ERROR: Failed to move ZIM to ${KIWIX_LIBRARY_DIR}"
    exit 1
fi

echo "${LOG_PREFIX} ZIM archived: ${KIWIX_LIBRARY_DIR}/${ZIM_NAME}"

TEMP_FILE="${MEMORY_FILE}.tmp"
CUTOFF_DATE=$(date -d "-${MAX_AGE_DAYS} days" +%Y-%m-%d 2>/dev/null || \
              date -v-${MAX_AGE_DAYS}d +%Y-%m-%d 2>/dev/null)

while IFS= read -r line; do
    DATE=$(echo "$line" | sed -n 's/^\[\([0-9-]*\)\].*/\1/p')
    CATEGORY=$(echo "$line" | sed -n 's/^\[[0-9-]*\] \[\([A-Z]*\)\].*/\1/p')

    if [ -z "$DATE" ] || [ -z "$CATEGORY" ]; then
        echo "$line" >> "${TEMP_FILE}"
        continue
    fi

    if [ "$CATEGORY" = "WORKFLOW" ] || [ "$CATEGORY" = "PERSONA" ]; then
        echo "$line" >> "${TEMP_FILE}"
        continue
    fi

    if [ "$DATE" \> "$CUTOFF_DATE" ] || [ "$DATE" = "$CUTOFF_DATE" ]; then
        echo "$line" >> "${TEMP_FILE}"
    fi

done < "${MEMORY_FILE}"

mv "${TEMP_FILE}" "${MEMORY_FILE}"
rm -rf "${STAGING_DIR}"

REMAINING=$(grep -c '\[' "${MEMORY_FILE}" 2>/dev/null || echo 0)
echo "${LOG_PREFIX} Complete. Consolidated ${ELIGIBLE_COUNT} entries."
echo "${LOG_PREFIX} ${REMAINING} entries remain in memory."
echo "${LOG_PREFIX} Restart your kiwix container to detect: ${KIWIX_LIBRARY_DIR}/${ZIM_NAME}"
