#!/bin/bash

# Configuration
PORT=${PORT:-10000}
FLASK_PORT=5000
STREAMLIT_PORT=8501

echo "🚀 Starting Snaphire Unified Portal..."

# 1. Configure Nginx with Railway's $PORT
echo "🔧 Configuring Nginx to listen on port $PORT..."
sed -i "s/\$PORT/$PORT/g" /etc/nginx/nginx.conf
nginx -t

# 2. Start Nginx directly in background (standalone)
echo "🌐 Starting Nginx Proxy..."
/usr/sbin/nginx -g "daemon on;"

# 3. Start Streamlit (Internal)
echo "🎬 Starting Streamlit Engine on port $STREAMLIT_PORT..."
export DOCKER_ENV=true
export RENDER=true
export RAILWAY_ENVIRONMENT=production
# Bind to 0.0.0.0 for standard docker networking and log to stdout for Railway diagnostics
python -m streamlit run streamlit_app.py \
    --server.port=$STREAMLIT_PORT \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableXsrfProtection=false \
    --server.enableCORS=false \
    --server.enableWebsocketCompression=false \
    --server.maxUploadSize=2000 \
    --server.maxMessageSize=200 \
    --server.baseUrlPath="/st-engine" \
    --browser.gatherUsageStats=false &

# 4. Wait for Streamlit to be ready
echo "⏳ Waiting for Streamlit to start on port $STREAMLIT_PORT..."
python3 -c "
import socket
import time
import sys

port = $STREAMLIT_PORT
host = '0.0.0.0'
start_time = time.time()
timeout = 30

while True:
    try:
        with socket.create_connection((host, port), timeout=1):
            print(f'✅ Streamlit is UP on port {port}')
            sys.exit(0)
    except (socket.timeout, ConnectionRefusedError, OSError):
        if time.time() - start_time > timeout:
            print(f'❌ Streamlit failed to start within {timeout}s')
            sys.exit(1)
        time.sleep(1)
" || exit 1

# 5. Start Flask (Internal via Gunicorn)
echo "🏗️ Starting Flask Portal on port $FLASK_PORT..."
gunicorn --bind 0.0.0.0:$FLASK_PORT \
     --workers 1 \
     --threads 1 \
     --timeout 600 \
     --access-logfile - \
     --error-logfile - \
     index:app
