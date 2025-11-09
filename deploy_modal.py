#!/usr/bin/env python3
"""
Deployment script for ChatGPT WebRTC Modal app.
This script handles the proper imports and deploys the Modal app.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the Modal app
from modal_app.app import app

if __name__ == "__main__":
    # This allows the script to be run directly with modal deploy
    pass
