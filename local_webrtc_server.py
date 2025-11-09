#!/usr/bin/env python3
"""
Local WebRTC server for testing ElectronSim without Modal.
Run: python local_webrtc_server.py
Then visit: http://localhost:8080
"""

import asyncio
import json
import logging
from pathlib import Path

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import VideoStreamTrack
from aiortc.contrib.media import VideoFrame
import numpy as np
import cv2

logging.basicConfig(level=logging.INFO)

# Store active peer connections
pcs = set()
counter = 0
button_rect = (40, 40, 240, 120)


class AppTrack(VideoStreamTrack):
    """Synthetic Electron-like window with clickable button"""
    
    kind = "video"

    def __init__(self):
        super().__init__()
        self.width = 640
        self.height = 360

    async def recv(self) -> VideoFrame:
        global counter, button_rect
        
        pts, time_base = await self.next_timestamp()
        x1, y1, x2, y2 = button_rect

        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:] = (30, 30, 30)
        
        # Title bar
        cv2.rectangle(img, (0, 0), (self.width, 32), (50, 50, 50), -1)
        cv2.putText(
            img, "ElectronSim - Click Button", (10, 22),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA
        )
        
        # Button
        cv2.rectangle(img, (x1, y1), (x2, y2), (60, 120, 250), -1)
        cv2.putText(
            img, "Click me", (x1 + 20, int((y1 + y2) / 2)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA
        )
        
        # Counter display
        cv2.putText(
            img, f"Counter: {counter}", (40, 170),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 220, 120), 2, cv2.LINE_AA
        )

        frame = VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


async def offer(request):
    """Handle WebRTC offer"""
    global counter
    
    params = await request.json()
    offer_sdp = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state: {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # Handle data channel for clicks
    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"Data channel opened: {channel.label}")

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
                        print(f"Button clicked! Counter: {counter}")
                        channel.send(json.dumps({"type": "counter", "value": counter}))
            except Exception as e:
                print(f"Error handling message: {e}")

    # Add video track
    pc.addTrack(AppTrack())

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
    content = open("webrtc/frontend/index_local.html").read()
    return web.Response(content_type="text/html", text=content)


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
    
    print("Starting local WebRTC server on http://localhost:8080")
    print("Open http://localhost:8080 in your browser")
    
    web.run_app(app, host="0.0.0.0", port=8080)



