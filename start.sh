#!/bin/bash

# Configuration
PORT=${PORT:-10000}
FLASK_PORT=5000
STREAMLIT_PORT=8501

echo "🚀 Starting Snaphire Unified Portal..."

# 1. Configure Nginx with Railway's $PORT
echo "🔧 Configuring Nginx to listen on port $PORT..."
sed -i "s/\$PORT/$PORT/g" /etc/nginx/nginx.conf

# 2. Start Nginx directly in background (standalone)
echo "🌐 Starting Nginx Proxy..."
/usr/sbin/nginx -g "daemon on;"

# Check if Nginx started
if [ $? -eq 0 ]; then
    echo "✅ Nginx started successfully"
else
    echo "❌ Nginx failed to start"
fi

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

# 4. Start Flask (Internal via Gunicorn)
echo "🏗️ Starting Flask Portal on port $FLASK_PORT..."
gunicorn --bind 0.0.0.0:$FLASK_PORT --timeout 120 index:app
