#!/usr/bin/env python3
"""
WebRTC server that runs the ACTUAL Electron app in a virtual display and streams it.
This is the Linux version that can be deployed to Modal.

Run locally on Linux: python electron_webrtc_linux.py
Deploy to Modal: python -m modal deploy electron_webrtc_modal.py
"""

import asyncio
import json
import logging
import subprocess
import signal
import os
from pathlib import Path

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.mediastreams import VideoStreamTrack
from aiortc.contrib.media import VideoFrame
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DISPLAY_NUM = ":99"
DISPLAY_WIDTH = 1100
DISPLAY_HEIGHT = 900
FPS = 20  # Lower FPS for better performance

# Store active peer connections and state
pcs = set()
electron_process = None
xvfb_process = None
ffmpeg_process = None


class ElectronDisplayTrack(VideoStreamTrack):
    """
    Captures the REAL Electron app display and streams it via WebRTC.
    Uses ffmpeg to capture from the virtual display where the Electron app is running.
    """

    kind = "video"

    def __init__(self):
        super().__init__()
        self.width = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT

        # Start ffmpeg to capture the display
        self.ffmpeg_process = subprocess.Popen(
            [
                'ffmpeg',
                '-f', 'x11grab',
                '-video_size', f'{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}',
                '-framerate', str(FPS),
                '-i', DISPLAY_NUM,
                '-pix_fmt', 'bgr24',
                '-f', 'rawvideo',
                '-'
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=DISPLAY_WIDTH * DISPLAY_HEIGHT * 3
        )

        logger.info(f"Started ffmpeg capture from display {DISPLAY_NUM} - capturing REAL Electron app")

    async def recv(self) -> VideoFrame:
        """Read a frame from ffmpeg and return it as a VideoFrame"""
        pts, time_base = await self.next_timestamp()

        # Read raw BGR frame from ffmpeg
        frame_size = self.width * self.height * 3
        raw_frame = await asyncio.get_event_loop().run_in_executor(
            None, self.ffmpeg_process.stdout.read, frame_size
        )

        if len(raw_frame) != frame_size:
            logger.warning(f"Incomplete frame read: {len(raw_frame)} bytes")
            # Return a black frame if we can't read
            img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        else:
            # Convert raw bytes to numpy array
            img = np.frombuffer(raw_frame, dtype=np.uint8).reshape((self.height, self.width, 3))

        frame = VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame

    def stop(self):
        """Stop the ffmpeg capture process"""
        if self.ffmpeg_process:
            self.ffmpeg_process.terminate()
            self.ffmpeg_process.wait()


def start_xvfb():
    """Start virtual X server (Xvfb)"""
    global xvfb_process

    logger.info(f"Starting Xvfb on display {DISPLAY_NUM}")
    xvfb_process = subprocess.Popen([
        'Xvfb',
        DISPLAY_NUM,
        '-screen', '0', f'{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}x24',
        '-ac',
        '+extension', 'GLX',
        '+render',
        '-noreset'
    ])

    # Wait a bit for Xvfb to start
    import time
    time.sleep(2)
    logger.info("Xvfb started")


def start_electron():
    """Start the REAL Electron app on the virtual display"""
    global electron_process

    env = os.environ.copy()
    env['DISPLAY'] = DISPLAY_NUM
    env['ELECTRON_DISABLE_SANDBOX'] = '1'

    logger.info("Starting REAL Electron app")

    # Get the path to main.js
    main_js_path = Path(__file__).parent / 'main.js'
    electron_process = subprocess.Popen(
        ['electron', str(main_js_path)],
        env=env,
        cwd=Path(__file__).parent
    )
    logger.info(f"Electron app started with PID {electron_process.pid}")


def stop_processes():
    """Stop Electron and Xvfb processes"""
    global electron_process, xvfb_process, ffmpeg_process

    if electron_process:
        logger.info("Stopping Electron app")
        electron_process.terminate()
        try:
            electron_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            electron_process.kill()
        electron_process = None

    if ffmpeg_process:
        logger.info("Stopping ffmpeg capture")
        ffmpeg_process.terminate()
        try:
            ffmpeg_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            ffmpeg_process.kill()
        ffmpeg_process = None

    if xvfb_process:
        logger.info("Stopping Xvfb")
        xvfb_process.terminate()
        try:
            xvfb_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            xvfb_process.kill()
        xvfb_process = None


def handle_input_event(data):
    """
    Forward input events to the REAL Electron app using xdotool.
    Supports mouse clicks, moves, and keyboard input.
    """
    event_type = data.get("type")

    try:
        if event_type == "mousemove":
            x, y = int(data["x"]), int(data["y"])
            subprocess.run([
                'xdotool', 'mousemove',
                '--window', os.environ.get('DISPLAY', DISPLAY_NUM),
                str(x), str(y)
            ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)

        elif event_type == "mousedown":
            x, y = int(data["x"]), int(data["y"])
            button = data.get("button", 1)
            subprocess.run([
                'xdotool', 'mousemove', str(x), str(y),
                'mousedown', str(button)
            ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)

        elif event_type == "mouseup":
            x, y = int(data["x"]), int(data["y"])
            button = data.get("button", 1)
            subprocess.run([
                'xdotool', 'mousemove', str(x), str(y),
                'mouseup', str(button)
            ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)

        elif event_type == "click":
            x, y = int(data["x"]), int(data["y"])
            button = data.get("button", 1)
            subprocess.run([
                'xdotool', 'mousemove', str(x), str(y),
                'click', str(button)
            ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)

        elif event_type == "keypress":
            key = data.get("key", "")
            if key:
                subprocess.run([
                    'xdotool', 'key', key
                ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)

        elif event_type == "type":
            text = data.get("text", "")
            if text:
                subprocess.run([
                    'xdotool', 'type', text
                ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)

    except Exception as e:
        logger.error(f"Error handling {event_type}: {e}")


async def offer(request):
    """Handle WebRTC offer from client"""
    params = await request.json()
    peer_id = params.get("peer_id", "default")

    logger.info(f"Received offer from peer {peer_id}")

    offer_sdp = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection(configuration=RTCConfiguration(
        iceServers=[
            RTCIceServer(urls="stun:stun.l.google.com:19302"),
            RTCIceServer(urls="stun:stun1.l.google.com:19302"),
        ]
    ))
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"Connection state for {peer_id}: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            pcs.discard(pc)

    # Handle data channel for input events
    @pc.on("datachannel")
    def on_datachannel(channel):
        logger.info(f"Data channel opened: {channel.label}")

        @channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
                handle_input_event(data)
            except Exception as e:
                logger.error(f"Error handling input: {e}")

    # Add video track - this will capture the REAL Electron app
    video_track = ElectronDisplayTrack()
    pc.addTrack(video_track)

    # Set remote description and create answer
    await pc.setRemoteDescription(offer_sdp)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}),
    )


async def index(request):
    """Serve the frontend HTML page"""
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Electron App - Real Remote Desktop</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        .header {
            background: #2d2d2d;
            padding: 16px 24px;
            border-bottom: 1px solid #404040;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 20px;
            font-weight: 600;
        }
        .controls {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        button {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }
        button.primary {
            background: #10a37f;
            color: white;
        }
        button.primary:hover {
            background: #0d8c6b;
        }
        button.secondary {
            background: #404040;
            color: white;
        }
        button.secondary:hover {
            background: #505050;
        }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .status {
            font-size: 14px;
            color: #a0a0a0;
        }
        .status.connected {
            color: #10a37f;
        }
        .status.error {
            color: #ef4444;
        }
        .video-container {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            background: #000;
            position: relative;
            overflow: hidden;
        }
        video {
            max-width: 100%;
            max-height: 100%;
            display: block;
            cursor: default;
            border: 2px solid #404040;
        }
        .loading {
            position: absolute;
            text-align: center;
        }
        .loading-spinner {
            width: 50px;
            height: 50px;
            border: 4px solid #404040;
            border-top-color: #10a37f;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .info {
            background: #2d2d2d;
            padding: 12px 24px;
            border-top: 1px solid #404040;
            font-size: 13px;
            color: #9ca3af;
        }
        .instructions {
            background: #1a1a1a;
            padding: 16px 24px;
            border-top: 1px solid #404040;
            font-size: 14px;
            color: #e0e0e0;
        }
        .instructions ul {
            margin: 8px 0;
            padding-left: 20px;
        }
        .instructions li {
            margin: 4px 0;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🖥️ ChatGPT Login - Remote Electron App</h1>
        <div class="controls">
            <span class="status" id="status">Disconnected</span>
            <button class="primary" id="connectBtn">Connect</button>
            <button class="secondary" id="disconnectBtn" style="display:none;">Disconnect</button>
        </div>
    </div>
    <div class="video-container">
        <div class="loading" id="loading" style="display:none;">
            <div class="loading-spinner"></div>
            <p style="margin-top: 16px;">Connecting to Electron app...</p>
        </div>
        <video id="remoteVideo" autoplay playsinline></video>
    </div>
    <div class="instructions">
        <strong>How to use this remote Electron app:</strong>
        <ul>
            <li>Click "Connect" to start the WebRTC session</li>
            <li>You'll see the real Electron app (ChatGPT Login) streaming live</li>
            <li>Use your mouse and keyboard to interact with the app</li>
            <li>The app will respond just like it would if running locally</li>
            <li>Login, browse, and export conversations - all from your browser!</li>
        </ul>
    </div>
    <div class="info">
        💡 This streams your actual Electron app via WebRTC. People can now use your app from any browser without installation!
    </div>

    <script>
        const statusEl = document.getElementById('status');
        const connectBtn = document.getElementById('connectBtn');
        const disconnectBtn = document.getElementById('disconnectBtn');
        const remoteVideo = document.getElementById('remoteVideo');
        const loadingEl = document.getElementById('loading');

        let pc = null;
        let dc = null;
        let peerId = null;

        function updateStatus(message, state = 'normal') {
            statusEl.textContent = message;
            statusEl.className = 'status';
            if (state === 'connected') statusEl.classList.add('connected');
            if (state === 'error') statusEl.classList.add('error');
            console.log(message);
        }

        function generatePeerId() {
            return 'peer_' + Math.random().toString(36).substring(7);
        }

        async function connect() {
            updateStatus('Connecting...', 'normal');
            loadingEl.style.display = 'block';
            connectBtn.disabled = true;

            peerId = generatePeerId();

            pc = new RTCPeerConnection({
                iceServers: [
                    { urls: 'stun:stun.l.google.com:19302' },
                    { urls: 'stun:stun1.l.google.com:19302' },
                ]
            });

            pc.onicecandidate = (e) => {
                if (e.candidate) {
                    console.log('ICE candidate:', e.candidate.candidate);
                }
            };

            pc.addTransceiver('video', { direction: 'recvonly' });

            pc.ontrack = (e) => {
                console.log('Received track:', e.track.kind);
                remoteVideo.srcObject = e.streams[0];
                updateStatus('Connected - Interact with the Electron app!', 'connected');
                loadingEl.style.display = 'none';
                connectBtn.style.display = 'none';
                disconnectBtn.style.display = 'inline-block';
            };

            pc.onconnectionstatechange = () => {
                console.log('Connection state:', pc.connectionState);
                if (pc.connectionState === 'failed') {
                    updateStatus('Connection failed', 'error');
                    disconnect();
                } else if (pc.connectionState === 'disconnected') {
                    updateStatus('Disconnected', 'normal');
                }
            };

            // Create data channel for input
            dc = pc.createDataChannel('input');
            dc.onopen = () => {
                console.log('Data channel opened - input enabled');
            };
            dc.onclose = () => {
                console.log('Data channel closed');
            };

            try {
                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);

                const response = await fetch('/offer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        peer_id: peerId,
                        sdp: offer.sdp,
                        type: offer.type
                    })
                });

                if (!response.ok) {
                    throw new Error('Server error: ' + response.status);
                }

                const answer = await response.json();
                await pc.setRemoteDescription({
                    type: answer.type,
                    sdp: answer.sdp
                });

                updateStatus('Establishing connection...', 'normal');
            } catch (error) {
                updateStatus('Error: ' + error.message, 'error');
                console.error(error);
                loadingEl.style.display = 'none';
                connectBtn.disabled = false;
            }
        }

        function disconnect() {
            if (pc) {
                pc.close();
                pc = null;
            }
            if (dc) {
                dc.close();
                dc = null;
            }
            remoteVideo.srcObject = null;
            updateStatus('Disconnected', 'normal');
            loadingEl.style.display = 'none';
            connectBtn.style.display = 'inline-block';
            connectBtn.disabled = false;
            disconnectBtn.style.display = 'none';
        }

        // Input forwarding
        function sendInput(data) {
            if (dc && dc.readyState === 'open') {
                dc.send(JSON.stringify(data));
            }
        }

        // Mouse events
        remoteVideo.addEventListener('mousemove', (e) => {
            if (!dc || dc.readyState !== 'open') return;
            const rect = remoteVideo.getBoundingClientRect();
            const x = Math.round((e.clientX - rect.left) * (remoteVideo.videoWidth / rect.width));
            const y = Math.round((e.clientY - rect.top) * (remoteVideo.videoHeight / rect.height));
            sendInput({ type: 'mousemove', x, y });
        });

        remoteVideo.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const rect = remoteVideo.getBoundingClientRect();
            const x = Math.round((e.clientX - rect.left) * (remoteVideo.videoWidth / rect.width));
            const y = Math.round((e.clientY - rect.top) * (remoteVideo.videoHeight / rect.height));
            sendInput({ type: 'mousedown', x, y, button: e.button + 1 });
        });

        remoteVideo.addEventListener('mouseup', (e) => {
            e.preventDefault();
            const rect = remoteVideo.getBoundingClientRect();
            const x = Math.round((e.clientX - rect.left) * (remoteVideo.videoWidth / rect.width));
            const y = Math.round((e.clientY - rect.top) * (remoteVideo.videoHeight / rect.height));
            sendInput({ type: 'mouseup', x, y, button: e.button + 1 });
        });

        remoteVideo.addEventListener('click', (e) => {
            e.preventDefault();
        });

        // Keyboard events
        document.addEventListener('keydown', (e) => {
            if (dc && dc.readyState === 'open') {
                e.preventDefault();
                sendInput({ type: 'keypress', key: e.key });
            }
        });

        // Button handlers
        connectBtn.addEventListener('click', connect);
        disconnectBtn.addEventListener('click', disconnect);
    </script>
</body>
</html>"""

    return web.Response(content_type="text/html", text=html)


async def on_startup(app):
    """Initialize the environment on server startup"""
    logger.info("Starting up...")
    start_xvfb()
    start_electron()


async def on_shutdown(app):
    """Clean up on server shutdown"""
    logger.info("Shutting down...")

    # Close all peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

    # Stop processes
    stop_processes()


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    logger.info("Received interrupt signal")
    stop_processes()
    exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)

    port = int(os.environ.get('PORT', 8080))

    logger.info("=" * 70)
    logger.info("Starting REAL Electron WebRTC Remote Desktop Server")
    logger.info("=" * 70)
    logger.info("Server: http://localhost:8080")
    logger.info("")
    logger.info("This streams the ACTUAL Electron app (main.js) via WebRTC")
    logger.info("Open the URL above in your browser and click 'Connect'")
    logger.info("")
    logger.info("What you'll see:")
    logger.info("- The real ChatGPT Login Electron app streaming live")
    logger.info("- Full mouse and keyboard interaction")
    logger.info("- Just like running the app locally, but in your browser!")
    logger.info("=" * 70)

    web.run_app(app, host="0.0.0.0", port=port)

