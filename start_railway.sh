#!/bin/bash

# Railway configuration
PORT=${PORT:-8080}
FLASK_PORT=5000
STREAMLIT_PORT=8501

echo "🚀 Starting Snaphire on Railway..."
echo "📍 External Port: $PORT"

# 1. Configure Nginx to listen on Railway's $PORT
echo "🔧 Configuring Nginx..."
cp nginx.conf /etc/nginx/sites-available/default
sed -i "s/\$PORT/$PORT/g" /etc/nginx/sites-available/default

# 2. Start Nginx
echo "🌐 Starting Nginx Proxy..."
service nginx start

# 3. Start Streamlit (Internal)
echo "🎬 Starting Streamlit Engine on port $STREAMLIT_PORT..."
export DOCKER_ENV=true
export RAILWAY_ENVIRONMENT=production
python -m streamlit run streamlit_app.py \
    --server.port=$STREAMLIT_PORT \
    --server.headless=true \
    --server.enableXsrfProtection=false \
    --server.enableCORS=false \
    --server.maxUploadSize=2000 \
    --server.baseUrlPath="/st-engine" \
    --browser.gatherUsageStats=false &

# 4. Start Flask (Internal via Gunicorn)
echo "🏗️ Starting Flask Portal on port $FLASK_PORT..."
gunicorn --bind 0.0.0.0:$FLASK_PORT --timeout 120 index:app
