#!/usr/bin/env bash
#
# Start the full multi-agent stack for local development.
#
# Usage:
#   ./dev.sh                  # Claude-powered agents + static test image
#   ./dev.sh --no-claude      # Deterministic-only agents
#   ./dev.sh --demo           # Use webcam instead of test image
#   ./dev.sh --demo --no-claude
#
# Ctrl-C to stop all agents.

set -e
cd "$(dirname "$0")"

CLAUDE_FLAG=""
SOURCE_FLAG="--image test_leaf.jpg"

for arg in "$@"; do
    case "$arg" in
        --no-claude) CLAUDE_FLAG="--no-claude" ;;
        --demo)      SOURCE_FLAG="--demo" ;;
        --image=*)   SOURCE_FLAG="--image ${arg#*=}" ;;
    esac
done

# Trap Ctrl-C to kill all background processes
cleanup() {
    echo ""
    echo "Stopping all agents..."
    kill $(jobs -p) 2>/dev/null
    wait 2>/dev/null
    echo "All agents stopped."
}
trap cleanup EXIT INT TERM

echo "=== Curiosity Detection — Multi-Agent Stack ==="
echo "  Source: $SOURCE_FLAG"
echo "  Claude: ${CLAUDE_FLAG:-enabled}"
echo ""

# Start agents in background
python agents/rover_agent.py     $CLAUDE_FLAG --http-port 8001 &
python agents/butterfly_agent.py $CLAUDE_FLAG --http-port 8002 &
python agents/body_agent.py      $CLAUDE_FLAG --http-port 8003 &
python agents/log_agent.py                    --http-port 8004 &

# Give agents a moment to start their HTTP servers
sleep 1

echo ""
echo "=== All agents running. Starting core loop... ==="
echo ""

# Core loop in foreground (always uses Claude for scene analysis)
python core_loop.py $SOURCE_FLAG \
    --http-agents http://localhost:8001 http://localhost:8002 http://localhost:8003 http://localhost:8004
