# ========= BASE IMAGE =========
# Use lightweight Python 3.11 base
FROM python:3.11-slim

# ========= SYSTEM DEPENDENCIES =========
# Install essential packages for Pipecat, audio, FFmpeg, etc.
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    portaudio19-dev \
    libsndfile1 \
    libasound2-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ========= ENVIRONMENT SETTINGS =========
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PYTHONPATH=/app
WORKDIR /app

# ========= DEPENDENCIES =========
# Copy dependency manifests first (for Docker layer caching)
COPY pyproject.toml uv.lock ./

# Install UV package manager if not already included
RUN pip install --no-cache-dir uv

# Install dependencies from the lockfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# ========= APP SOURCE CODE =========
COPY ./geny-bot.py /app/bot.py

# ========= ENV VARIABLES =========
# These should be provided at runtime (not baked into the image)
# e.g. GOOGLE_API_KEY, MCP_SERVER_URL, MCP_API_KEY, etc.
ENV ENV=local

# ========= ENTRYPOINT =========
CMD ["python", "bot.py"]
