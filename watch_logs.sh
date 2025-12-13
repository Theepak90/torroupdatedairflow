#!/bin/bash

# Watch logs for file discovery
# Usage: ./watch_logs.sh [airflow|backend|both]

MODE=${1:-both}
PROJECT_DIR="/Users/theepak/Desktop/torroairflow"

echo "🔍 Watching logs for file discovery..."
echo ""

if [ "$MODE" == "airflow" ] || [ "$MODE" == "both" ]; then
    echo "📊 Airflow Scheduler Logs (Ctrl+C to stop):"
    echo "=========================================="
    
    # Find latest DAG run log
    LATEST_LOG=$(find "$PROJECT_DIR/airflow/logs/dag_id=azure_blob_discovery" -name "*.log" -type f -exec ls -t {} + 2>/dev/null | head -1)
    
    if [ -n "$LATEST_LOG" ]; then
        echo "📄 Latest DAG log: $LATEST_LOG"
        echo ""
        tail -f "$LATEST_LOG" 2>/dev/null &
        TAIL_PID=$!
    else
        echo "⚠️  No DAG logs found yet. Waiting for first run..."
        # Watch scheduler log instead
        tail -f "$PROJECT_DIR/airflow/logs/scheduler/latest/scheduler.log" 2>/dev/null &
        TAIL_PID=$!
    fi
    
    if [ "$MODE" == "airflow" ]; then
        wait $TAIL_PID
        exit 0
    fi
fi

if [ "$MODE" == "backend" ] || [ "$MODE" == "both" ]; then
    echo ""
    echo "🔧 Backend API Logs:"
    echo "==================="
    
    if [ -f "/tmp/backend.log" ]; then
        tail -f /tmp/backend.log 2>/dev/null &
        BACKEND_PID=$!
    else
        echo "⚠️  Backend log file not found. Backend might be running in foreground."
        echo "   Check the terminal where you started the backend."
    fi
    
    if [ "$MODE" == "backend" ]; then
        wait $BACKEND_PID 2>/dev/null
        exit 0
    fi
fi

# Wait for both
if [ "$MODE" == "both" ]; then
    echo ""
    echo "✅ Watching both Airflow and Backend logs..."
    echo "   Press Ctrl+C to stop"
    wait
fi
