#!/usr/bin/env bash
# A/B test runner for php-modernization skill evals
# Runs each eval prompt WITHOUT skill (baseline) and WITH skill, collecting metrics.
#
# Usage: bash evals/run-ab-test.sh [--indices 0,3,5]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVALS_FILE="$SCRIPT_DIR/evals.json"
RESULTS_DIR="$SCRIPT_DIR/results"
SKILL_DIR="$(dirname "$SCRIPT_DIR")/skills/php-modernization"
SYSTEM_HINT="Respond directly with code and explanation. Do not use file tools."

mkdir -p "$RESULTS_DIR"

EVAL_COUNT=$(python3 -c "import json; print(len(json.load(open('$EVALS_FILE'))))")

# Parse optional --indices flag for selective runs
if [[ "${1:-}" == "--indices" && -n "${2:-}" ]]; then
    IFS=',' read -ra INDICES <<< "$2"
else
    INDICES=($(seq 0 $((EVAL_COUNT - 1))))
fi

echo "Running A/B tests for ${#INDICES[@]} of $EVAL_COUNT evals..."

for i in "${INDICES[@]}"; do
    EVAL_NAME=$(python3 -c "import json; print(json.load(open('$EVALS_FILE'))[$i]['name'])")
    EVAL_PROMPT=$(python3 -c "import json,sys; sys.stdout.write(json.load(open('$EVALS_FILE'))[$i]['prompt'])")

    echo "[$((i+1))/$EVAL_COUNT] Testing: $EVAL_NAME"

    # WITHOUT skill (baseline)
    echo "  Running WITHOUT skill..."
    START_A=$(date +%s%N)
    claude --print --model sonnet --max-turns 3 --dangerously-skip-permissions \
        --disable-slash-commands \
        --append-system-prompt "$SYSTEM_HINT" \
        -p "$EVAL_PROMPT" > "$RESULTS_DIR/${EVAL_NAME}_without.txt" 2>/dev/null || true
    END_A=$(date +%s%N)
    DURATION_A=$(( (END_A - START_A) / 1000000 ))

    # WITH skill
    echo "  Running WITH skill..."
    START_B=$(date +%s%N)
    claude --print --model sonnet --max-turns 3 --dangerously-skip-permissions \
        --disable-slash-commands \
        --plugin-dir "$SKILL_DIR/.." \
        --append-system-prompt "$SYSTEM_HINT" \
        -p "$EVAL_PROMPT" > "$RESULTS_DIR/${EVAL_NAME}_with.txt" 2>/dev/null || true
    END_B=$(date +%s%N)
    DURATION_B=$(( (END_B - START_B) / 1000000 ))

    # Collect metrics
    SIZE_A=$(wc -c < "$RESULTS_DIR/${EVAL_NAME}_without.txt")
    SIZE_B=$(wc -c < "$RESULTS_DIR/${EVAL_NAME}_with.txt")
    LINES_A=$(wc -l < "$RESULTS_DIR/${EVAL_NAME}_without.txt")
    LINES_B=$(wc -l < "$RESULTS_DIR/${EVAL_NAME}_with.txt")

    echo "  WITHOUT: ${SIZE_A}B, ${LINES_A} lines, ${DURATION_A}ms"
    echo "  WITH:    ${SIZE_B}B, ${LINES_B} lines, ${DURATION_B}ms"

    # Store metrics as JSON
    python3 -c "
import json
metrics = {
    'name': '$EVAL_NAME',
    'without': {'bytes': $SIZE_A, 'lines': $LINES_A, 'duration_ms': $DURATION_A},
    'with': {'bytes': $SIZE_B, 'lines': $LINES_B, 'duration_ms': $DURATION_B}
}
with open('$RESULTS_DIR/${EVAL_NAME}_metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)
"
done

echo ""
echo "A/B tests complete. Results in $RESULTS_DIR/"
