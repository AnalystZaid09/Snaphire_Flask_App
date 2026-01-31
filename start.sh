#!/bin/bash

# Configuration
PORT=${PORT:-10000}
FLASK_PORT=5000
STREAMLIT_PORT=8501

echo "🚀 Starting Snaphire Unified Portal..."

# 1. Inject Render Port into Nginx config
echo "🔧 Configuring Nginx to listen on port $PORT..."
sed -i "s/\$PORT/$PORT/g" /etc/nginx/sites-available/default

# 2. Start Nginx
echo "🌐 Starting Nginx Proxy..."
service nginx start

# 3. Start Streamlit (Internal)
echo "🎬 Starting Streamlit Engine on port $STREAMLIT_PORT..."
export DOCKER_ENV=true
export RENDER=true
python -m streamlit run streamlit_app.py \
    --server.port=$STREAMLIT_PORT \
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
