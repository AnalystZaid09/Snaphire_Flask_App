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
python -m streamlit run streamlit_app.py \
    --server.port=$STREAMLIT_PORT \
    --server.address=127.0.0.1 \
    --server.headless=true \
    --server.enableXsrfProtection=false \
    --server.enableCORS=false \
    --server.enableWebsocketCompression=false \
    --server.maxUploadSize=2000 \
    --server.maxMessageSize=200 \
    --server.baseUrlPath="/st-engine" \
    --browser.gatherUsageStats=false &

# 4. Wait for Streamlit to be ready
echo "⏳ Waiting for Streamlit on port $STREAMLIT_PORT..."
sleep 5

# 5. Start Flask (Internal via Gunicorn)
echo "🏗️ Starting Flask Portal on port $FLASK_PORT..."
gunicorn --bind 0.0.0.0:$FLASK_PORT \
     --workers 1 \
     --threads 1 \
     --timeout 600 \
     --access-logfile - \
     --error-logfile - \
     index:app
