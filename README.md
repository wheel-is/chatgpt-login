# ChatGPT Conversation Exporter

## Current Desktop Flow
- Launches an Electron shell pointed at the real ChatGPT login screen.
- Watches navigation for a post-login chat URL, then pulls:
  - Session cookies and the access token (`session_credentials.json`).
  - Full paginated conversation list (`conversation_history.json`).
  - Per-conversation transcripts dropped under `user-<id>/<conversationId>.json`.
- Leaves the browser window active for continued use; reruns after manual restart.

## Remote "Web" Variant (Future Work)
- Host the Electron app inside a GPU-enabled container/VM.
- Capture the window output, encode it (H.264), and stream to the browser over WebRTC.
- Relay keyboard/mouse events back over a data channel and inject them into the remote session.
- Run the same export pipeline server-side; surface downloads to the end user once complete.
- Requires session orchestration (spawn/kill), state storage, and strict TLS/authentication.
- **Modal support:** Modal provides first-party WebRTC infrastructure (see [Real-time object detection with WebRTC](https://modal.com/docs/examples/webrtc_yolo)) built on `modal_webrtc`, so a hosted variant can lean on their serverless WebRTC primitives instead of rolling our own signaling/media stack.

### Modal WebRTC Prototype (Modal WebRTC + YOLO example)
This repo now uses Modal's official WebRTC YOLO example (`07_web_endpoints/webrtc/webrtc_yolo.py`). The example streams webcam video to Modal, runs YOLO object detection on a GPU, and streams annotated video back to the browser. It's a production-grade reference that we can adapt to stream the ChatGPT login flow.

**Files:**
- `webrtc/webrtc_yolo.py` – Modal app (copied directly from Modal examples)
- `webrtc/modal_webrtc.py` – helper classes for WebRTC signaling/peers
- `webrtc/frontend/` – browser client served by the Modal app
- `deploy_webrtc.py` – deployment entrypoint that imports the example package

**Deploy:**

```bash
python -m modal deploy /Users/willroberts/Desktop/chatgptlogin/deploy_webrtc.py
```

After deployment, Modal prints the web UI URL (format: `https://<account>--example-webrtc-yolo-webcamobjdet-web.modal.run`).

**Test the stream:**

1. Visit the deployed URL in your browser
2. Click "Record"
3. **Allow camera permission** when prompted (check address bar)
4. You should see YOLO boxes overlayed on your video (processed on Modal's GPU)

This confirms Modal's WebRTC pipeline (WebSocket signaling, STUN ICE negotiation, GPU media processing, streaming back) works end-to-end.

**Next steps to make this a hosted ChatGPT login flow:**
- Replace YOLO processing with Playwright capturing a remote Chromium instance showing the ChatGPT login flow
- Use the FastAPI data channel hooks in `ModalWebRtcPeer` to forward mouse/keyboard events from the browser to Playwright
- Implement per-user session orchestration, authentication, and cleanup routines
- Extract and return session cookies/tokens after successful login

## Possible User Incentives
1. **Cash/credit per conversation** – direct value exchange for data.
2. **Interactive visualizations** – map their ChatGPT usage: topics, sentiment, time trends.
3. **Buzzfeed-style personality quiz** – “What your chats say about you.” Fun hook, low effort.

The desktop collector is production-ready for experimentation. The streamed Electron approach gives us the “web” UX without surrendering cookie/token access; it’s the next serious build-out.
