#!/usr/bin/env python3
"""
Deployment entrypoint for Modal's WebRTC YOLO example.

Run:
  python -m modal deploy /Users/willroberts/Desktop/chatgptlogin/deploy_webrtc.py
"""

import os
import sys

# Ensure repo root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the Modal app object from the YOLO example package
from webrtc.webrtc_yolo import app  # noqa: F401

if __name__ == "__main__":
    pass
