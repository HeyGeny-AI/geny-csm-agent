# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    portaudio19-dev \
    libsndfile1 \
    libasound2-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install MCP from git repository
RUN pip install --no-cache-dir git+https://github.com/modelcontextprotocol/python-sdk.git

# Copy application code
COPY . .

# Run the bot
CMD ["python", "geny-bot.py"]