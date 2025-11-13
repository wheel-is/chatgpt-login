FROM debian:bookworm-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    xvfb \
    x11-xserver-utils \
    xdotool \
    ffmpeg \
    nodejs \
    npm \
    libgtk-3-0 \
    libnotify4 \
    libnss3 \
    libxss1 \
    libxtst6 \
    xauth \
    libgbm1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    ca-certificates \
    fonts-liberation \
    wget \
    python3 \
    python3-pip \
    python3-venv \
    coturn \
    xclip \
    && rm -rf /var/lib/apt/lists/*

# Install Electron globally
RUN npm install -g electron

# Set up Python environment
WORKDIR /app
COPY requirements-webrtc.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements-webrtc.txt

# Copy application files
COPY main.js .
COPY preload.js .
COPY package.json .
COPY local_webrtc_server.py .
COPY chatgpt-login-widget.js .
COPY demo-widget.html .

# Expose port for WebRTC server
EXPOSE 8080

# Start script
CMD ["python3", "local_webrtc_server.py"]

