#!/usr/bin/env python3
"""
Modal deployment for REAL Electron WebRTC streaming.
This runs the ACTUAL Electron app (main.js) in a container and streams it via WebRTC.

Deploy: python -m modal deploy electron_webrtc_modal.py
Visit: https://<account>--electron-webrtc-serve.modal.run
"""

import modal
import json

# Create Modal image with all required dependencies for REAL Electron app
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "xvfb",           # Virtual display
        "x11-xserver-utils",  # xdpyinfo and other X utilities
        "xdotool",        # Input simulation
        "ffmpeg",         # Screen capture
        "nodejs",         # Node.js for installing Electron
        "npm",            # npm for installing Electron
        "libgtk-3-0",     # GTK for Electron
        "libnotify4",     # Notifications
        "libnss3",        # NSS for Electron
        "libxss1",        # Screen saver
        "libxtst6",       # X11 testing
        "xauth",          # X authentication
        "libgbm1",        # Generic Buffer Management
        "libasound2",     # ALSA sound
        "libatk-bridge2.0-0",
        "libatk1.0-0",
        "libcups2",
        "libdrm2",
        "libxcomposite1",
        "libxdamage1",
        "libxfixes3",
        "libxrandr2",
        "ca-certificates",
        "fonts-liberation",
        "wget",
    )
    .run_commands(
        "npm install -g electron",  # Install Electron globally
    )
    .pip_install(
        "aiohttp>=3.9.0",
        "aiortc>=1.6.0",
        "numpy>=1.24.0",
        "opencv-python-headless>=4.8.0",
    )
    .add_local_dir(
        ".",
        remote_path="/app",
        ignore=lambda p: any(
            excluded in str(p) for excluded in [
                "node_modules",
                "__pycache__",
                ".git",
                "user-",
                "dojarob_gmail_com",
                "7r6hhchss5_privaterelay_appleid_com",
            ]
        ) or p.is_relative_to(".git") or p.is_relative_to("node_modules") or p.is_relative_to("__pycache__"),
    )
)

app = modal.App("electron-webrtc", image=image)


@app.function(
    image=image,
    timeout=3600,  # 1 hour timeout
)
@modal.asgi_app()
def serve():
    """
    Serve the Electron WebRTC app using aiohttp.
    """
    import asyncio
    import logging
    import subprocess
    import os
    from pathlib import Path
    from aiohttp import web
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
    from aiortc.mediastreams import VideoStreamTrack
    from aiortc.contrib.media import VideoFrame
    import numpy as np
    
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Configuration - matches the Electron app window size (1100x900)
    DISPLAY_NUM = ":99"
    DISPLAY_WIDTH = 1100
    DISPLAY_HEIGHT = 900
    FPS = 20  # Lower FPS for Modal to save resources

    # Store active peer connections
    pcs = set()
    xvfb_process = None
    electron_process = None
    ffmpeg_process = None

    class ElectronDisplayTrack(VideoStreamTrack):
        """Captures the REAL Electron app display and streams it via WebRTC"""

        kind = "video"

        def __init__(self):
            super().__init__()
            self.width = DISPLAY_WIDTH
            self.height = DISPLAY_HEIGHT

            # Start ffmpeg to capture the display where the REAL Electron app is running
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
        """Start virtual X server"""
        nonlocal xvfb_process

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

        import time
        time.sleep(3)
        logger.info("Xvfb started")

    def start_electron():
        """Start the REAL Electron app"""
        nonlocal electron_process

        env = os.environ.copy()
        env['DISPLAY'] = DISPLAY_NUM
        env['ELECTRON_DISABLE_SANDBOX'] = '1'

        logger.info("Starting REAL Electron app (main.js)")

        # The Electron app will run in the virtual display
        electron_process = subprocess.Popen(
            ['electron', '/app/main.js'],
            env=env,
            cwd='/app'
        )
        logger.info(f"REAL Electron app started with PID {electron_process.pid}")

    def handle_input_event(data):
        """Forward input events using xdotool"""
        event_type = data.get("type")
        
        try:
            if event_type == "mousemove":
                x, y = int(data["x"]), int(data["y"])
                subprocess.run([
                    'xdotool', 'mousemove', str(x), str(y)
                ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)
                
            elif event_type in ("mousedown", "mouseup", "click"):
                x, y = int(data["x"]), int(data["y"])
                button = data.get("button", 1)
                cmd = ['xdotool', 'mousemove', str(x), str(y)]
                if event_type == "mousedown":
                    cmd.extend(['mousedown', str(button)])
                elif event_type == "mouseup":
                    cmd.extend(['mouseup', str(button)])
                else:
                    cmd.extend(['click', str(button)])
                subprocess.run(cmd, env={'DISPLAY': DISPLAY_NUM}, timeout=1)
                
            elif event_type == "keypress":
                key = data.get("key", "")
                if key:
                    subprocess.run([
                        'xdotool', 'key', key
                    ], env={'DISPLAY': DISPLAY_NUM}, timeout=1)
                    
        except Exception as e:
            logger.error(f"Error handling {event_type}: {e}")

    async def offer(request):
        """Handle WebRTC offer"""
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

        video_track = ElectronDisplayTrack()
        pc.addTrack(video_track)

        await pc.setRemoteDescription(offer_sdp)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }),
        )

    async def index(request):
        """Serve the frontend"""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>ChatGPT Login - Remote Electron App</title>
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
            <li>You'll see the real ChatGPT Login Electron app streaming live</li>
            <li>Use your mouse and keyboard to interact with the app</li>
            <li>The app will respond just like it would if running locally</li>
            <li>Login, browse, and export conversations - all from your browser!</li>
        </ul>
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
                    console.log('ICE candidate:', e.candidate);
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

            dc = pc.createDataChannel('input');
            dc.onopen = () => console.log('Data channel opened');
            dc.onclose = () => console.log('Data channel closed');

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
            if (pc) { pc.close(); pc = null; }
            if (dc) { dc.close(); dc = null; }
            remoteVideo.srcObject = null;
            updateStatus('Disconnected', 'normal');
            loadingEl.style.display = 'none';
            connectBtn.style.display = 'inline-block';
            connectBtn.disabled = false;
            disconnectBtn.style.display = 'none';
        }

        function sendInput(data) {
            if (dc && dc.readyState === 'open') {
                dc.send(JSON.stringify(data));
            }
        }

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

        remoteVideo.addEventListener('click', (e) => e.preventDefault());

        document.addEventListener('keydown', (e) => {
            if (dc && dc.readyState === 'open') {
                e.preventDefault();
                sendInput({ type: 'keypress', key: e.key });
            }
        });

        connectBtn.addEventListener('click', connect);
        disconnectBtn.addEventListener('click', disconnect);
    </script>
</body>
</html>"""
        
        return web.Response(content_type="text/html", text=html)

    # Initialize environment
    start_xvfb()
    start_electron()

    # Create and configure web app
    web_app = web.Application()
    web_app.router.add_get("/", index)
    web_app.router.add_post("/offer", offer)
    
    return web_app

