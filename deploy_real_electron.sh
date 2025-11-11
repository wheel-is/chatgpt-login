#!/bin/bash
# Deploy the REAL Electron WebRTC app to Modal

echo "🚀 Deploying REAL Electron WebRTC app to Modal..."
echo ""
echo "This will stream your ACTUAL Electron app (main.js) via WebRTC"
echo "People can use your ChatGPT Login app from any browser!"
echo ""

# Deploy to Modal
python -m modal deploy electron_webrtc_modal.py

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Your Electron app is now available at the Modal URL above."
echo "People can now use your ChatGPT Login app remotely via WebRTC!"
