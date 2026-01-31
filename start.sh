#!/bin/bash

# Configuration
PORT=${PORT:-10000}
STREAMLIT_PORT=8501

echo "🚀 Starting Snaphire Unified Portal (Streamlit-Only Mode)..."

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

# 2. Start Nginx in background
echo "🌐 Starting Nginx Proxy..."
/usr/sbin/nginx -g "daemon on;"

# 3. Start Streamlit as FOREGROUND process (this is the main process Railway monitors)
echo "🎬 Starting Streamlit Engine on port $STREAMLIT_PORT (Foreground)..."
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
