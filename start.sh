#!/bin/bash

# Configuration
PORT=${PORT:-10000}
FLASK_PORT=5000
STREAMLIT_PORT=8501

echo "🚀 Starting Snaphire Unified Portal..."

# 0. Optimization Flags
export PYTHONMALLOC=malloc
export PYTHONOPTIMIZE=1
export PYTHONUNBUFFERED=1
export DOCKER_ENV=true
export RENDER=true
export RAILWAY_ENVIRONMENT=production

# 1. Configure Nginx with Railway's $PORT
echo "🔧 Configuring Nginx to listen on port $PORT..."
sed -i "s/\$PORT/$PORT/g" /etc/nginx/nginx.conf
nginx -t

# 2. Start Nginx
echo "🌐 Starting Nginx Proxy..."
/usr/sbin/nginx -g "daemon on;"

# 3. Start Flask FIRST (Background - so portal works immediately)
echo "🏗️ Starting Flask Portal on port $FLASK_PORT..."
gunicorn --bind 0.0.0.0:$FLASK_PORT \
     --workers 1 \
     --threads 1 \
     --timeout 120 \
     --preload \
     --max-requests 100 \
     --access-logfile - \
     --error-logfile - \
     index:app &

# 4. Wait for Flask to be ready
echo "⏳ Waiting for Flask..."
sleep 3

# 5. Start Streamlit as FOREGROUND (main process)
echo "🎬 Starting Streamlit Engine on port $STREAMLIT_PORT..."
exec python -m streamlit run streamlit_app.py \
    --server.port=$STREAMLIT_PORT \
    --server.address=127.0.0.1 \
    --server.headless=true \
    --server.enableXsrfProtection=false \
    --server.enableCORS=false \
    --server.enableWebsocketCompression=false \
    --server.maxUploadSize=2000 \
    --server.maxMessageSize=200 \
    --server.baseUrlPath="/st-engine" \
    --browser.gatherUsageStats=false
