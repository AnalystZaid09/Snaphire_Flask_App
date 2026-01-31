#!/bin/bash

# Railway configuration
PORT=${PORT:-8080}
FLASK_PORT=5000
STREAMLIT_PORT=8501

echo "🚀 Starting Snaphire on Railway..."
echo "📍 External Port: $PORT"
echo "📍 Internal Flask: $FLASK_PORT"
echo "📍 Internal Streamlit: $STREAMLIT_PORT"

# 1. Configure Nginx to listen on Railway's $PORT
echo "🔧 Configuring Nginx..."
mkdir -p /run/nginx
# Overwrite the MAIN nginx.conf with our self-contained version
cp nginx.conf /etc/nginx/nginx.conf
sed -i "s/\$PORT/$PORT/g" /etc/nginx/nginx.conf

# 2. Start Nginx directly in background
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
export RAILWAY_ENVIRONMENT=production
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
# Use 1 worker to stay within 512MB RAM
echo "🏗️ Starting Flask Portal on port $FLASK_PORT..."
exec gunicorn --bind 0.0.0.0:$FLASK_PORT --timeout 120 --workers 1 --log-level info index:app
