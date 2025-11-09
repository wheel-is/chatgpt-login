import modal
from pathlib import Path

from .modal_webrtc import ModalWebRtcPeer, ModalWebRtcSignalingServer


# Minimal image for synthetic video + signaling
base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi[standard]==0.115.4",
        "aiortc==1.11.0",
        "opencv-python-headless==4.11.0.86",
        "numpy==2.3.4",
        "shortuuid==1.0.13",
    )
)

app = modal.App("electron-sim-webrtc", image=base_image)


@app.cls(
    image=base_image,
    secrets=[modal.Secret.from_name("turn-credentials")],
)
class ElectronSimPeer(ModalWebRtcPeer):
    async def initialize(self):
        self.counter = 0
        self.button_rect = (40, 40, 240, 120)  # x1, y1, x2, y2

    async def setup_streams(self, peer_id: str):
        from aiortc.mediastreams import VideoStreamTrack
        from aiortc.contrib.media import VideoFrame
        import numpy as np
        import cv2

        pc = self.pcs[peer_id]

        @pc.on("datachannel")
        def on_datachannel(channel):
            @channel.on("message")
            def on_message(msg):
                try:
                    import json as _json
                    data = _json.loads(msg)
                    if data.get("type") == "click":
                        x, y = int(data.get("x", 0)), int(data.get("y", 0))
                        x1, y1, x2, y2 = self.button_rect
                        if x1 <= x <= x2 and y1 <= y <= y2:
                            self.counter += 1
                            channel.send(_json.dumps({"type": "counter", "value": self.counter}))
                except Exception as e:
                    print(f"Input parse error: {e}")

        class AppTrack(VideoStreamTrack):
            kind = "video"

            def __init__(self, get_state):
                super().__init__()
                self.get_state = get_state
                self.width = 640
                self.height = 360

            async def recv(self) -> VideoFrame:
                pts, time_base = await self.next_timestamp()
                counter, rect = self.get_state()
                x1, y1, x2, y2 = rect

                img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
                img[:] = (30, 30, 30)
                # Title bar
                cv2.rectangle(img, (0, 0), (self.width, 32), (50, 50, 50), -1)
                cv2.putText(img, "ElectronSim - Click Button", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
                # Button
                cv2.rectangle(img, (x1, y1), (x2, y2), (60, 120, 250), -1)
                cv2.putText(img, "Click me", (x1 + 20, int((y1 + y2) / 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
                # Counter display
                cv2.putText(img, f"Counter: {counter}", (40, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 220, 120), 2, cv2.LINE_AA)

                frame = VideoFrame.from_ndarray(img, format="bgr24")
                frame.pts = pts
                frame.time_base = time_base
                return frame

        def get_state():
            return self.counter, self.button_rect

        pc.addTrack(AppTrack(get_state))

    async def get_turn_servers(self, peer_id=None, msg=None) -> dict:
        import os
        
        # Get TURN credentials from Modal secrets
        creds = {
            "username": os.environ.get("TURN_USERNAME", "openrelayproject"),
            "credential": os.environ.get("TURN_CREDENTIAL", "openrelayproject"),
        }
        
        return {
            "type": "turn_servers",
            "ice_servers": [
                {"urls": "stun:stun.l.google.com:19302"},
                {"urls": "stun:stun1.l.google.com:19302"},
                # Free TURN relay servers
                {"urls": "turn:openrelay.metered.ca:80", **creds},
                {"urls": "turn:openrelay.metered.ca:443", **creds},
                {"urls": "turn:openrelay.metered.ca:443?transport=tcp", **creds},
            ],
        }


# Serve the minimal frontend that connects via WebSocket and shows the video + sends clicks
this_directory = Path(__file__).parent.resolve()
server_image = base_image.add_local_dir(this_directory / "frontend", remote_path="/frontend")


@app.cls(image=server_image)
class ElectronSimServer(ModalWebRtcSignalingServer):
    def get_modal_peer_class(self):
        return ElectronSimPeer

    def initialize(self):
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles

        self.web_app.mount("/static", StaticFiles(directory="/frontend"))

        @self.web_app.get("/")
        async def root():
            html = open("/frontend/index.html").read()
            return HTMLResponse(content=html)