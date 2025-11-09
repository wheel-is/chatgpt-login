"""
Simple WebRTC on Modal - identical to local_webrtc_server.py pattern.
Deploy: python -m modal deploy simple_webrtc.py
Visit: https://<account>--simple-webrtc-serve.modal.run
"""

import modal
from typing import Set

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "fastapi[standard]",
    "aiortc",
    "numpy",
    "opencv-python-headless",
)

app = modal.App("simple-webrtc", image=image)

# Global state for all connections
peer_connections_map = {}
counter = 0
button_rect = (40, 40, 240, 120)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, RTCIceCandidate
from aiortc.sdp import candidate_from_sdp
from aiortc.mediastreams import VideoStreamTrack
from aiortc.contrib.media import VideoFrame
import numpy as np
import cv2
import json

web_app = FastAPI()

class AppTrack(VideoStreamTrack):
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
        cv2.rectangle(img, (0, 0), (self.width, 32), (50, 50, 50), -1)
        cv2.putText(img, "ElectronSim - Click Button", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.rectangle(img, (x1, y1), (x2, y2), (60, 120, 250), -1)
        cv2.putText(img, "Click me", (x1 + 20, int((y1 + y2) / 2)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, f"Counter: {counter}", (40, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 220, 120), 2, cv2.LINE_AA)

        frame = VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame

@web_app.post("/offer")
async def handle_offer(request: Request):
        global counter

        body = await request.json()
        peer_id = body.get("peer_id", "default")

        pc = RTCPeerConnection(configuration=RTCConfiguration(
            iceServers=[
                RTCIceServer(urls="stun:stun.l.google.com:19302"),
                RTCIceServer(urls="stun:stun1.l.google.com:19302"),
                RTCIceServer(urls="stun:stun2.l.google.com:19302"),
                RTCIceServer(urls="stun:stun3.l.google.com:19302"),
                RTCIceServer(urls="stun:stun4.l.google.com:19302"),
                # Try some alternative TURN servers
                RTCIceServer(urls="turn:numb.viagenie.ca", username="webrtc@live.com", credential="muazkh"),
                RTCIceServer(urls="turn:192.158.29.39:3478?transport=udp", username="28224511:1379330808", credential="JZEOEt2V3Qb0y27GRntt2u2PAY="),
                RTCIceServer(urls="turn:192.158.29.39:3478?transport=tcp", username="28224511:1379330808", credential="JZEOEt2V3Qb0y27GRntt2u2PAY="),
            ]
        ))
        peer_connections_map[peer_id] = pc

        @pc.on("datachannel")
        def on_datachannel(channel):
            @channel.on("message")
            def on_message(message):
                global counter
                try:
                    data = json.loads(message)
                    if data.get("type") == "click":
                        x, y = int(data["x"]), int(data["y"])
                        x1, y1, x2, y2 = button_rect
                        if x1 <= x <= x2 and y1 <= y <= y2:
                            counter += 1
                            channel.send(json.dumps({"type": "counter", "value": counter}))
                except Exception as e:
                    print(f"Click error: {e}")

        @pc.on("connectionstatechange")
        async def on_state():
            print(f"Connection state for {peer_id}: {pc.connectionState}")
            if pc.connectionState in ("failed", "closed"):
                await pc.close()
                peer_connections_map.pop(peer_id, None)

        pc.addTrack(AppTrack())

        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return JSONResponse({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})

@web_app.post("/ice_candidate")
async def handle_ice_candidate(request: Request):
    body = await request.json()
    peer_id = body.get("peer_id", "default")

    pc = peer_connections_map.get(peer_id)
    if not pc:
        return JSONResponse({"error": "Peer connection not found"}, status_code=404)

    candidate_data = body.get("candidate")
    if not candidate_data:
        return JSONResponse({"error": "No candidate provided"}, status_code=400)

    try:
        # Parse the SDP candidate string into an RTCIceCandidate object
        candidate_string = candidate_data["candidate"]
        ice_candidate = candidate_from_sdp(candidate_string)

        # Set the sdpMid and sdpMLineIndex from the client data
        ice_candidate.sdpMid = candidate_data.get("sdpMid")
        ice_candidate.sdpMLineIndex = candidate_data.get("sdpMLineIndex")

        await pc.addIceCandidate(ice_candidate)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        print(f"ICE candidate error for peer {peer_id}: {e}")
        import traceback
        print(f"Full error: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=400)
    
@web_app.get("/")
async def serve_index():
        html = """<!DOCTYPE html>
<html><head><title>ElectronSim WebRTC</title><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#0b0f19;color:#e5e7eb}.container{max-width:960px;margin:24px auto;padding:16px}video{width:100%;max-height:70vh;background:#000;border:1px solid #374151;border-radius:8px;cursor:pointer}button{padding:12px 20px;background:#10a37f;color:#fff;border:0;border-radius:8px;font-weight:600;cursor:pointer;margin:8px 4px}button:hover{background:#0d8c6b}button.secondary{background:#374151}.status{margin:12px 0;color:#9ca3af;font-size:14px}</style>
</head><body><div class="container"><h1>ElectronSim (Modal WebRTC)</h1><p class="status" id="status">Click Connect to start</p>
<div><button id="start">Connect</button><button id="stop" class="secondary" style="display:none">Disconnect</button></div>
<div style="margin-top:16px"><video id="remoteVideo" autoplay playsinline></video></div></div>
<script>const statusEl=document.getElementById('status'),startBtn=document.getElementById('start'),stopBtn=document.getElementById('stop'),remoteVideo=document.getElementById('remoteVideo');let pc=null,dc=null,peerId=null;function updateStatus(e){statusEl.textContent=e,console.log(e)}function generatePeerId(){return'peer_'+Math.random().toString(36).substring(7)}async function connect(){updateStatus('Creating peer connection...'),peerId=generatePeerId(),pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'},{urls:'stun:stun1.l.google.com:19302'},{urls:'stun:stun2.l.google.com:19302'},{urls:'stun:stun3.l.google.com:19302'},{urls:'stun:stun4.l.google.com:19302'},{urls:'turn:numb.viagenie.ca',username:'webrtc@live.com',credential:'muazkh'},{urls:'turn:192.158.29.39:3478?transport=udp',username:'28224511:1379330808',credential:'JZEOEt2V3Qb0y27GRntt2u2PAY='},{urls:'turn:192.158.29.39:3478?transport=tcp',username:'28224511:1379330808',credential:'JZEOEt2V3Qb0y27GRntt2u2PAY='}]}),pc.onicecandidate=async e=>{if(e.candidate){try{await fetch('/ice_candidate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({peer_id:peerId,candidate:{candidate:e.candidate.candidate,sdpMid:e.candidate.sdpMid,sdpMLineIndex:e.candidate.sdpMLineIndex}})})}catch(t){console.error('ICE candidate send error:',t)}}},pc.addTransceiver('video',{direction:'recvonly'}),pc.ontrack=e=>{updateStatus('Video stream received! Click on the blue button.'),remoteVideo.srcObject=e.streams[0]},pc.onconnectionstatechange=()=>{updateStatus('Connection: '+pc.connectionState),'connected'===pc.connectionState&&updateStatus('Connected! Click the blue button to increment counter.')},dc=pc.createDataChannel('input'),dc.onopen=()=>updateStatus('Ready - click on the blue button!'),dc.onmessage=e=>{const t=JSON.parse(e.data);'counter'===t.type&&updateStatus('Counter: '+t.value+' (click again!)')};const e=await pc.createOffer();await pc.setLocalDescription(e),updateStatus('Sending offer to server...');const t=await fetch('/offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({peer_id:peerId,sdp:e.sdp,type:e.type})}),n=await t.json();if(n.error)return void updateStatus('Server error: '+n.error);updateStatus('Received answer, establishing connection...'),await pc.setRemoteDescription({type:n.type,sdp:n.sdp})}function disconnect(){updateStatus('Disconnected');try{pc&&pc.close()}catch{}pc=null,dc=null,remoteVideo.srcObject=null}remoteVideo.addEventListener('click',e=>{if(!dc||'open'!==dc.readyState)return void updateStatus('Data channel not open yet');const t=remoteVideo.getBoundingClientRect(),n=Math.round((e.clientX-t.left)*(640/t.width)),o=Math.round((e.clientY-t.top)*(360/t.height));console.log(`Sending click: ${n}, ${o}`),dc.send(JSON.stringify({type:'click',x:n,y:o}))}),startBtn.addEventListener('click',async()=>{startBtn.style.display='none',stopBtn.style.display='inline-block';try{await connect()}catch(e){updateStatus('Error: '+e.message),console.error(e),startBtn.style.display='inline-block',stopBtn.style.display='none'}}),stopBtn.addEventListener('click',()=>{disconnect(),stopBtn.style.display='none',startBtn.style.display='inline-block'});</script></body></html>"""
        
        return HTMLResponse(content=html)


@app.function()
@modal.asgi_app()
def serve():
    return web_app
