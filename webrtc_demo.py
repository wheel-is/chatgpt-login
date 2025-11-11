#!/usr/bin/env python3
"""
Standalone WebRTC demo server - simulates Electron app with clickable UI.
Run: python webrtc_demo.py
Then visit: http://localhost:8080
"""

import asyncio
import json
import logging
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.mediastreams import VideoStreamTrack
from aiortc.contrib.media import VideoFrame
import numpy as np
import cv2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store active peer connections
pcs = set()
counter = 0
button_rect = (40, 40, 240, 120)


class SimulatedElectronTrack(VideoStreamTrack):
    """Simulates an Electron window with clickable button"""
    
    kind = "video"

    def __init__(self):
        super().__init__()
        self.width = 1100
        self.height = 900

    async def recv(self) -> VideoFrame:
        global counter, button_rect
        
        pts, time_base = await self.next_timestamp()
        x1, y1, x2, y2 = button_rect

        # Create dark background like Electron
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:] = (15, 23, 42)  # Dark blue-gray like the app
        
        # Title bar
        cv2.rectangle(img, (0, 0), (self.width, 40), (45, 45, 45), -1)
        cv2.putText(
            img, "ChatGPT Login - Electron App (Simulated)", (20, 27),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA
        )
        
        # Main content area
        cv2.putText(
            img, "Electron App Remote Desktop Demo", (40, 100),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (229, 231, 235), 2, cv2.LINE_AA
        )
        
        cv2.putText(
            img, "This simulates your Electron app running remotely", (40, 150),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (156, 163, 175), 1, cv2.LINE_AA
        )
        
        cv2.putText(
            img, "Click the button below to interact:", (40, 190),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (156, 163, 175), 1, cv2.LINE_AA
        )
        
        # Clickable button
        cv2.rectangle(img, (x1, y1), (x2, y2), (16, 163, 127), -1)
        cv2.putText(
            img, "Click me!", (x1 + 30, int((y1 + y2) / 2) + 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA
        )
        
        # Counter display
        cv2.putText(
            img, f"Button clicks: {counter}", (40, 270),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (16, 163, 127), 2, cv2.LINE_AA
        )
        
        # Instructions
        instructions = [
            "How it works:",
            "- This video is streamed via WebRTC",
            "- Your clicks are sent back to the server",
            "- The real Electron app would run on Linux with Xvfb",
            "- On macOS, we simulate it to demonstrate the concept",
            "",
            "In production, you'd see your actual Electron app here!"
        ]
        
        y_pos = 350
        for line in instructions:
            cv2.putText(
                img, line, (40, y_pos),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (156, 163, 175), 1, cv2.LINE_AA
            )
            y_pos += 35

        frame = VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


async def offer(request):
    """Handle WebRTC offer"""
    global counter
    
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
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            await pc.close()
            pcs.discard(pc)

    # Handle data channel for clicks
    @pc.on("datachannel")
    def on_datachannel(channel):
        logger.info(f"Data channel opened: {channel.label}")

        @channel.on("message")
        def on_message(message):
            global counter
            try:
                data = json.loads(message)
                if data.get("type") == "click":
                    x, y = int(data.get("x", 0)), int(data.get("y", 0))
                    x1, y1, x2, y2 = button_rect
                    if x1 <= x <= x2 and y1 <= y <= y2:
                        counter += 1
                        logger.info(f"Button clicked! Counter: {counter}")
                        channel.send(json.dumps({"type": "counter", "value": counter}))
            except Exception as e:
                logger.error(f"Error handling message: {e}")

    # Add video track
    pc.addTrack(SimulatedElectronTrack())

    # Set remote description and create answer
    await pc.setRemoteDescription(offer_sdp)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}),
    )


async def index(request):
    """Serve the frontend"""
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Electron WebRTC Demo</title>
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
            cursor: pointer;
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
    </style>
</head>
<body>
    <div class="header">
        <h1>🖥️ Electron App - WebRTC Remote Desktop Demo</h1>
        <div class="controls">
            <span class="status" id="status">Disconnected</span>
            <button class="primary" id="connectBtn">Connect</button>
            <button class="secondary" id="disconnectBtn" style="display:none;">Disconnect</button>
        </div>
    </div>
    <div class="video-container">
        <div class="loading" id="loading" style="display:none;">
            <div class="loading-spinner"></div>
            <p style="margin-top: 16px;">Connecting...</p>
        </div>
        <video id="remoteVideo" autoplay playsinline></video>
    </div>
    <div class="info">
        💡 This simulates your Electron app streaming via WebRTC. Click the green button in the video to test interaction!
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
                updateStatus('Connected - Click the green button!', 'connected');
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
            dc.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.type === 'counter') {
                    console.log('Counter updated:', data.value);
                }
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

        // Click handler
        remoteVideo.addEventListener('click', (e) => {
            if (!dc || dc.readyState !== 'open') {
                console.log('Data channel not ready');
                return;
            }
            
            const rect = remoteVideo.getBoundingClientRect();
            const x = Math.round((e.clientX - rect.left) * (remoteVideo.videoWidth / rect.width));
            const y = Math.round((e.clientY - rect.top) * (remoteVideo.videoHeight / rect.height));
            
            console.log('Sending click:', x, y);
            dc.send(JSON.stringify({ type: 'click', x, y }));
        });

        // Button handlers
        connectBtn.addEventListener('click', connect);
        disconnectBtn.addEventListener('click', disconnect);
    </script>
</body>
</html>"""
    
    return web.Response(content_type="text/html", text=html)


async def on_shutdown(app):
    """Clean up peer connections on shutdown"""
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


if __name__ == "__main__":
    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)
    
    logger.info("=" * 60)
    logger.info("Starting Electron WebRTC Demo Server")
    logger.info("=" * 60)
    logger.info("Server: http://localhost:8080")
    logger.info("")
    logger.info("This simulates streaming your Electron app via WebRTC")
    logger.info("Open the URL above in your browser and click 'Connect'")
    logger.info("=" * 60)
    
    web.run_app(app, host="0.0.0.0", port=8080)

