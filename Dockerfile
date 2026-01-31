# Switch to the full Python 3.11 image (it includes build-essential and is more stable on Render)
FROM python:3.11

# Install only Nginx (full image already has curl and build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy Nginx config to the right place for standalone execution
COPY nginx.conf /etc/nginx/nginx.conf

# Make start script executable
RUN chmod +x start.sh

# Expose the port (Render will override this)
EXPOSE 10000

# Start everything
CMD ["./start.sh"]
