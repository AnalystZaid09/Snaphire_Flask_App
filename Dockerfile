# Use official Python 3.11 slim image
FROM python:3.11-slim

# Install Nginx and other system dependencies
RUN apt-get update && apt-get install -y \
    nginx \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy Nginx config to the right place
COPY nginx.conf /etc/nginx/sites-available/default

# Make start script executable
RUN chmod +x start.sh

# Expose the port (Render will override this)
EXPOSE 10000

# Start everything
CMD ["./start.sh"]
