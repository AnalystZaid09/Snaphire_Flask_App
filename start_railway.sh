#!/bin/bash

# Railway simplified startup - no nginx needed
PORT=${PORT:-8080}

echo "🚀 Starting Snaphire on Railway..."
echo "📍 Port: $PORT"

# Set environment variables
export DOCKER_ENV=true
export RAILWAY_ENVIRONMENT=production

# Start Flask directly on Railway's PORT
echo "🏗️ Starting Flask Portal..."
exec gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 2 index:app
