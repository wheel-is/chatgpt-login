# WebRTC Electron Streaming - Docker Setup with TURN

Stream your Electron app via WebRTC in a Docker container with TURN relay for NAT traversal.

## Quick Start

```bash
# Build and run
docker-compose up --build

# Access the web interface
open http://localhost:8080
```

## What's Running

- **WebRTC Server**: HTTP server on port 8080
- **TURN Server**: STUN/TURN relay on ports 3478 (TCP/UDP) and 5349 (TLS/UDP)
- **Virtual Display**: Xvfb provides headless X11 display
- **Electron App**: Your actual Electron application
- **Screen Capture**: ffmpeg captures the display for streaming

## Manual Docker Commands

```bash
# Build the image
docker build -t electron-webrtc .

# Run the container
docker run -p 8080:8080 electron-webrtc

# Run with logs
docker run -p 8080:8080 -it electron-webrtc
```

## How It Works

1. **Xvfb** creates a virtual X11 display inside the container
2. **Electron** app runs on the virtual display
3. **ffmpeg** captures the display output
4. **aiortc** streams the video via WebRTC to your browser
5. **xdotool** forwards mouse/keyboard input from browser to Electron

## Usage

1. Visit http://localhost:8080 in your browser
2. Click **Connect**
3. You'll see the Electron app streaming in your browser
4. Interact with it using your mouse and keyboard

## Troubleshooting

### Container won't start
```bash
# Check logs
docker-compose logs -f

# Restart
docker-compose restart
```

### Can't connect to WebRTC
- Make sure ports 8080, 3478, 5349 are not in use
- Check browser console for errors
- Check container logs: `docker-compose logs -f`
- Try using Chrome/Edge (better WebRTC support)
- TURN server should handle NAT traversal automatically

### Video is black
- Electron might still be loading - wait 10-15 seconds
- Check container logs for Electron errors

## Stopping

```bash
# Stop the container
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

