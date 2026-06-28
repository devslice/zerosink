# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    ZEROSINK_DB_PATH=/app/data/zerosink.db \
    ZEROSINK_WEB_HOST=0.0.0.0 \
    ZEROSINK_WEB_PORT=80 \
    ZEROSINK_DNS_HOST=0.0.0.0 \
    ZEROSINK_DNS_PORT=53

# Set working directory
WORKDIR /app

# Install system dependencies (build-essential needed for compiling certain dependencies if wheels aren't present)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies list
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application directories
COPY backend/ ./backend
COPY static/ ./static

# Create persistent data directory
RUN mkdir -p /app/data

# Expose DNS engine and web dashboard ports
EXPOSE 53/udp
EXPOSE 53/tcp
EXPOSE 80/tcp


# Run the unified process
CMD ["python", "-m", "backend.main"]
