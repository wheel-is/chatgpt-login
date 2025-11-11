import asyncio
import json
import subprocess
import os
import threading
import time
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.mediastreams import VideoStreamTrack
from aiortc.contrib.media import VideoFrame
import numpy as np
import modal

# Global state for the application
pcs = set()
xvfb_process = None
electron_process = None
ffmpeg_process = None
process_lock = threading.Lock()

# Configuration - matches the Electron app window size (1100x900)
DISPLAY_NUM = ":99"
DISPLAY_WIDTH = 1100
DISPLAY_HEIGHT = 900
FPS = 20

class ElectronDisplayTrack(VideoStreamTrack):
    """Captures the REAL Electron app display and streams it via WebRTC"""

    kind = "video"

    def __init__(self):
        super().__init__()
        self.width = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT
        # Use the global ffmpeg process
        self.ffmpeg_process = ffmpeg_process

    async def recv(self) -> VideoFrame:
        """Read a frame from ffmpeg and return it as a VideoFrame"""
        pts, time_base = await self.next_timestamp()

        if self.ffmpeg_process is None or self.ffmpeg_process.poll() is not None:
            # Return a black frame if ffmpeg is not running
            img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        else:
            try:
                frame_size = self.width * self.height * 3
                raw_frame = await asyncio.get_event_loop().run_in_executor(
                    None, self.ffmpeg_process.stdout.read, frame_size
                )

                if len(raw_frame) != frame_size:
                    # Return a black frame if we can't read complete frame
                    img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
                else:
                    # Convert raw bytes to numpy array
                    img = np.frombuffer(raw_frame, dtype=np.uint8).reshape((self.height, self.width, 3))
            except Exception as e:
                print(f"Error reading from ffmpeg: {e}")
                img = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        frame = VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


def ensure_processes_running():
    """Make sure Xvfb, Electron, and ffmpeg are online before streaming."""
    global xvfb_process, electron_process, ffmpeg_process

    with process_lock:
        try:
            if xvfb_process is None or xvfb_process.poll() is not None:
                print(f"Starting Xvfb on display {DISPLAY_NUM}")
                xvfb_process = subprocess.Popen([
                    'Xvfb',
                    DISPLAY_NUM,
                    '-screen', '0', f'{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}x24',
                    '-ac',
                    '+extension', 'GLX',
                    '+render',
                    '-noreset'
                ])
                time.sleep(3)
                print("Xvfb started")
            else:
                print("Xvfb already running")

            if electron_process is None or electron_process.poll() is not None:
                env = os.environ.copy()
                env['DISPLAY'] = DISPLAY_NUM
                env['ELECTRON_DISABLE_SANDBOX'] = '1'
                print("Starting REAL Electron app (main.js)")
                electron_process = subprocess.Popen(
                    ['electron', '/app/main.js'],
                    env=env,
                    cwd='/app'
                )
                time.sleep(5)
                print("REAL Electron app started")
            else:
                print("REAL Electron app already running")

            if ffmpeg_process is None or ffmpeg_process.poll() is not None:
                print("Starting ffmpeg capture")
                ffmpeg_process = subprocess.Popen([
                    'ffmpeg',
                    '-f', 'x11grab',
                    '-video_size', f'{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}',
                    '-framerate', str(FPS),
                    '-i', DISPLAY_NUM,
                    '-pix_fmt', 'bgr24',
                    '-f', 'rawvideo',
                    '-'
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=DISPLAY_WIDTH * DISPLAY_HEIGHT * 3)
                time.sleep(2)
                print("ffmpeg capture started")
            else:
                print("ffmpeg capture already running")
        except Exception as exc:
            print(f"Failed while ensuring processes are running: {exc}")
            raise


HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>ChatGPT Login - Remote Electron App</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #121212;
            color: #e0e0e0;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        .header {
            background: #1f1f1f;
            border-bottom: 1px solid #2a2a2a;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 20px;
            font-weight: 600;
        }
        .controls { display: flex; gap: 12px; align-items: center; }
        button {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s ease;
            font-size: 14px;
        }
        button.primary { background: #10a37f; color: #fff; }
        button.primary:hover { background: #0d8c6b; }
        button.secondary { background: #2e2e2e; color: #fff; }
        button.secondary:hover { background: #3a3a3a; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .status { font-size: 14px; color: #a0a0a0; }
        .status.connected { color: #10a37f; }
        .status.error { color: #ef4444; }
        .video-container {
            flex: 1;
            background: #000;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }
        video {
            width: 100%;
            height: 100%;
            object-fit: contain;
            background: #000;
        }
        .loading {
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(0, 0, 0, 0.65);
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 14px;
        }
        .footer {
            padding: 14px 24px;
            font-size: 13px;
            color: #909090;
            background: #181818;
            border-top: 1px solid #2a2a2a;
        }
        .footer a { color: #10a37f; text-decoration: none; }
        .footer a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="header">
        <h1>ChatGPT Login - Remote Electron App</h1>
        <div class="controls">
            <span id="status" class="status">Idle</span>
            <button id="connectBtn" class="primary">Connect</button>
            <button id="disconnectBtn" class="secondary" style="display: none;">Disconnect</button>
        </div>
    </div>
    <div class="video-container">
        <video id="remoteVideo" autoplay playsinline></video>
        <div id="loading" class="loading" style="display: none;">Connecting to Electron app...</div>
    </div>
    <div class="footer">
        Use your mouse and keyboard inside the video to control the remote Electron session. Keyboard focus follows the window.
    </div>
    <script>
        const OFFER_URL = 'https://penumbra--electron-webrtc-offer.modal.run';
        const statusEl = document.getElementById('status');
        const connectBtn = document.getElementById('connectBtn');
        const disconnectBtn = document.getElementById('disconnectBtn');
        const remoteVideo = document.getElementById('remoteVideo');
        const loadingEl = document.getElementById('loading');
        const peerId = 'peer_' + Math.random().toString(36).slice(2, 10);

        let pc = null;
        let dc = null;

        function updateStatus(message, kind = 'normal') {
            statusEl.textContent = message;
            statusEl.className = 'status' + (kind ? ' ' + kind : '');
        }

        function setConnected(connected) {
            if (connected) {
                connectBtn.style.display = 'none';
                disconnectBtn.style.display = 'inline-block';
                disconnectBtn.disabled = false;
            } else {
                connectBtn.style.display = 'inline-block';
                connectBtn.disabled = false;
                disconnectBtn.style.display = 'none';
            }
        }

        async function connect() {
            if (pc) {
                disconnect();
            }

            try {
                connectBtn.disabled = true;
                updateStatus('Connecting...', 'normal');
                loadingEl.style.display = 'block';

                pc = new RTCPeerConnection({
                    iceServers: [
                        { urls: 'stun:stun.l.google.com:19302' },
                        { urls: 'stun:stun1.l.google.com:19302' }
                    ]
                });

                pc.addTransceiver('video', { direction: 'recvonly' });

                pc.ontrack = (event) => {
                    remoteVideo.srcObject = event.streams[0];
                    updateStatus('Connected - Interact with the Electron app!', 'connected');
                    setConnected(true);
                    loadingEl.style.display = 'none';
                };

                pc.onconnectionstatechange = () => {
                    const state = pc.connectionState;
                    console.log('Connection state:', state);
                    if (state === 'failed' || state === 'disconnected' || state === 'closed') {
                        updateStatus('Connection ' + state, 'error');
                        disconnect();
                    }
                };

                pc.oniceconnectionstatechange = () => {
                    console.log('ICE state:', pc.iceConnectionState);
                };

                dc = pc.createDataChannel('input', { ordered: true });
                dc.onclose = () => {
                    console.log('Data channel closed');
                };

                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);

                const response = await fetch(OFFER_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        peer_id: peerId,
                        sdp: pc.localDescription.sdp,
                        type: pc.localDescription.type
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
                console.error(error);
                updateStatus('Error: ' + error.message, 'error');
                loadingEl.style.display = 'none';
                setConnected(false);
                if (pc) {
                    pc.close();
                    pc = null;
                }
                if (dc) {
                    dc.close();
                    dc = null;
                }
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
            loadingEl.style.display = 'none';
            updateStatus('Disconnected', 'normal');
            setConnected(false);
        }

        function sendInput(data) {
            if (dc && dc.readyState === 'open') {
                dc.send(JSON.stringify(data));
            }
        }

        remoteVideo.addEventListener('mousemove', (e) => {
            if (!dc || dc.readyState !== 'open' || !remoteVideo.videoWidth) {
                return;
            }
            const rect = remoteVideo.getBoundingClientRect();
            const scaleX = remoteVideo.videoWidth / rect.width;
            const scaleY = remoteVideo.videoHeight / rect.height;
            const x = Math.round((e.clientX - rect.left) * scaleX);
            const y = Math.round((e.clientY - rect.top) * scaleY);
            sendInput({ type: 'mousemove', x, y });
        });

        ['mousedown', 'mouseup'].forEach((eventName) => {
            remoteVideo.addEventListener(eventName, (e) => {
                e.preventDefault();
                if (!dc || dc.readyState !== 'open' || !remoteVideo.videoWidth) {
                    return;
                }
                const rect = remoteVideo.getBoundingClientRect();
                const scaleX = remoteVideo.videoWidth / rect.width;
                const scaleY = remoteVideo.videoHeight / rect.height;
                const x = Math.round((e.clientX - rect.left) * scaleX);
                const y = Math.round((e.clientY - rect.top) * scaleY);
                const button = e.button + 1;
                sendInput({ type: eventName, x, y, button });
            });
        });

        document.addEventListener('keydown', (e) => {
            if (!dc || dc.readyState !== 'open') {
                return;
            }
            e.preventDefault();
            sendInput({ type: 'keypress', key: e.key });
        });

        remoteVideo.addEventListener('contextmenu', (e) => e.preventDefault());
        connectBtn.addEventListener('click', connect);
        disconnectBtn.addEventListener('click', disconnect);
        window.addEventListener('beforeunload', disconnect);
    </script>
</body>
</html>"""


def handle_input_event(data):
    """Forward input events to the REAL Electron app using xdotool"""
    event_type = data.get("type")

    try:
        if event_type == "mousemove":
            x, y = int(data["x"]), int(data["y"])
            subprocess.run([
                'xdotool', 'mousemove', str(x), str(y)
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

    except Exception as e:
        print(f"Error handling {event_type}: {e}")

# Create FastAPI app
web_app = web.Application()

@web_app.get("/", response_class=web.Response)
async def index(request):
    """Serve the frontend HTML page"""
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
        }
        video {
            max-width: 100%;
            max-height: 100%;
            display: block;
            background: #000;
        }
        .loading {
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(0, 0, 0, 0.75);
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 14px;
        }
        .instructions {
            padding: 16px 24px;
            font-size: 14px;
            line-height: 1.6;
            background: #1f1f1f;
            border-top: 1px solid #404040;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>ChatGPT Login - Remote Electron App</h1>
        <div class="controls">
            <span id="status" class="status">Idle</span>
            <button id="connectBtn" class="primary">Connect</button>
            <button id="disconnectBtn" class="secondary" style="display: none;">Disconnect</button>
        </div>
    </div>
    <div class="video-container">
        <video id="remoteVideo" autoplay playsinline></video>
        <div id="loading" class="loading" style="display: none;">
            Connecting to Electron app...
        </div>
    </div>
    <div class="instructions">
        <p><strong>Remote Electron App controls:</strong></p>
        <ul>
            <li>Click the <strong>Connect</strong> button to initiate the WebRTC session.</li>
            <li>Once connected, interact using your mouse and keyboard inside the streamed window.</li>
            <li>Use <strong>Disconnect</strong> to end the session and release resources.</li>
        </ul>
    </div>
    <script>
        const OFFER_URL = 'https://penumbra--electron-webrtc-offer.modal.run';
        const statusEl = document.getElementById('status');
        const connectBtn = document.getElementById('connectBtn');
        const disconnectBtn = document.getElementById('disconnectBtn');
        const remoteVideo = document.getElementById('remoteVideo');
        const loadingEl = document.getElementById('loading');
        const peerId = 'peer_' + Math.random().toString(36).slice(2, 10);

        let pc = null;
        let dc = null;

        function updateStatus(message, kind = 'normal') {
            statusEl.textContent = message;
            statusEl.className = 'status';
            statusEl.classList.add(kind === 'error' ? 'error' : kind === 'connected' ? 'connected' : '');
        }

        function resetUI() {
            connectBtn.disabled = false;
            connectBtn.style.display = 'inline-block';
            disconnectBtn.style.display = 'none';
            disconnectBtn.disabled = false;
        }

        async function connect() {
            try {
                connectBtn.disabled = true;
                updateStatus('Connecting...', 'normal');
                loadingEl.style.display = 'block';

                pc = new RTCPeerConnection({
                    iceServers: [
                        { urls: 'stun:stun.l.google.com:19302' },
                        { urls: 'stun:stun1.l.google.com:19302' }
                    ]
                });

                pc.ontrack = (event) => {
                    remoteVideo.srcObject = event.streams[0];
                    updateStatus('Connected - Interact with the Electron app!', 'connected');
                    connectBtn.style.display = 'none';
                    disconnectBtn.style.display = 'inline-block';
                    loadingEl.style.display = 'none';
                };

                pc.oniceconnectionstatechange = () => {
                    console.log('ICE state:', pc.iceConnectionState);
                };

                pc.onconnectionstatechange = () => {
                    console.log('Connection state:', pc.connectionState);
                    if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {
                        updateStatus('Connection ' + pc.connectionState, 'error');
                        disconnect();
                    }
                };

                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);

                const response = await fetch(OFFER_URL, {
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
                console.error(error);
                updateStatus('Error: ' + error.message, 'error');
                loadingEl.style.display = 'none';
                resetUI();
                if (pc) {
                    pc.close();
                    pc = null;
                }
            }
        }

        function disconnect() {
            if (pc) {
                pc.close();
                pc = null;
            }
            remoteVideo.srcObject = null;
            updateStatus('Disconnected', 'normal');
            loadingEl.style.display = 'none';
            resetUI();
        }

        connectBtn.addEventListener('click', connect);
        disconnectBtn.addEventListener('click', disconnect);
    </script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")

@web_app.post("/offer")
async def offer(request):
    """Handle WebRTC offer"""
    params = await request.json()
    peer_id = params.get("peer_id", "default")

    print(f"Received offer from peer {peer_id}")

    offer_sdp = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    try:
        pc = RTCPeerConnection(configuration=RTCConfiguration(
            iceServers=[
                RTCIceServer(urls="stun:stun.l.google.com:19302"),
                RTCIceServer(urls="stun:stun1.l.google.com:19302"),
            ]
        ))
        pcs.add(pc)
        print("Created RTCPeerConnection successfully")
    except Exception as e:
        print(f"Error creating RTCPeerConnection: {e}")
        return {"error": f"RTCPeerConnection creation failed: {e}"}

    ice_complete = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def on_icegatheringstatechange():
        print(f"ICE gathering state for {peer_id}: {pc.iceGatheringState}")
        if pc.iceGatheringState == "complete" and not ice_complete.is_set():
            ice_complete.set()

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state for {peer_id}: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            pcs.discard(pc)

    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"Data channel opened: {channel.label}")

        @channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
                handle_input_event(data)
            except Exception as e:
                print(f"Error handling input: {e}")

    # Add video track - this will capture the REAL Electron app
    video_track = ElectronDisplayTrack()
    pc.addTrack(video_track)

    try:
        await pc.setRemoteDescription(offer_sdp)
        print("Set remote description successfully")
        answer = await pc.createAnswer()
        print("Created answer successfully")
        await pc.setLocalDescription(answer)
        print("Set local description successfully")
        if pc.iceGatheringState != "complete":
            try:
                await asyncio.wait_for(ice_complete.wait(), timeout=10)
                print("ICE gathering completed")
            except asyncio.TimeoutError:
                print("ICE gathering timed out; proceeding with partial candidates")
    except Exception as e:
        print(f"Error in WebRTC negotiation: {e}")
        return {"error": f"WebRTC negotiation failed: {e}"}

    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }),
    )

@app.function(
    image=image,
    timeout=3600,  # 1 hour timeout
)
@modal.fastapi_endpoint(method="GET")
def serve():
    """Serve the REAL Electron WebRTC app."""
    ensure_processes_running()
    return HTMLResponse(content=HTML_PAGE)
