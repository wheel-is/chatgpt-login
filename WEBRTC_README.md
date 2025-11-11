# Electron WebRTC Remote Desktop - REAL App Streaming

This system streams your **ACTUAL Electron app** (main.js) to a web browser using WebRTC, allowing remote interaction with the app's UI from any modern browser. No installation required - users can use your ChatGPT Login app from anywhere!

## Architecture

The system consists of:

1. **Virtual Display (Xvfb)**: Runs the Electron app in a headless X11 server
2. **Screen Capture (ffmpeg)**: Captures the virtual display as video frames
3. **WebRTC Server**: Streams video to browsers and forwards user input
4. **Input Forwarding (xdotool)**: Sends mouse/keyboard events to the Electron app

## Local Development

### Prerequisites

Install the required system packages:

```bash
# macOS (using Homebrew)
brew install xvfb ffmpeg xdotool

# Linux (Debian/Ubuntu)
sudo apt-get update
sudo apt-get install -y xvfb ffmpeg xdotool \
    x11-xserver-utils libgtk-3-0 libnotify4 \
    libnss3 libxss1 libxtst6 xauth libgbm1
```

### Install Python Dependencies

```bash
pip install -r requirements_webrtc.txt
```

### Run Locally

```bash
python electron_webrtc_server.py
```

Then open your browser to: **http://localhost:8765**

Click "Connect" and you'll see the Electron app streaming live. You can interact with it using your mouse and keyboard.

## Modal Deployment (Cloud) - RECOMMENDED

Deploy to Modal for remote access from anywhere - this runs your REAL Electron app in the cloud:

### Prerequisites

```bash
pip install modal
python -m modal setup
```

### Deploy

```bash
# Easy deployment script (recommended)
./deploy_real_electron.sh

# Or manually:
python -m modal deploy electron_webrtc_modal.py
```

After deployment, Modal will provide you with a URL like:
```
https://your-account--electron-webrtc-serve.modal.run
```

Visit that URL in your browser to interact with your **REAL Electron app** remotely!

### What You'll See

When you visit the Modal URL:
1. Click "Connect" to establish WebRTC connection
2. Your actual ChatGPT Login Electron app appears in the browser
3. Use mouse/keyboard to interact just like running locally
4. Login to ChatGPT, browse conversations, export data - all remotely!

## Local Linux Testing

Test on a Linux machine before deploying to Modal:

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y xvfb ffmpeg xdotool electron

# Run the real Electron app
python electron_webrtc_linux.py
```

Then visit `http://localhost:8080` to test.

## How It Works

### Video Streaming

1. Xvfb creates a virtual X11 display (`:99`)
2. The Electron app runs on this virtual display
3. ffmpeg captures the display at 20-30 FPS
4. Video frames are encoded and sent via WebRTC to the browser

### Input Forwarding

1. Browser captures mouse moves, clicks, and keyboard events
2. Events are sent through WebRTC Data Channel to the server
3. Server uses `xdotool` to inject these events into the virtual display
4. Electron app receives the events as if they were local

### Network Topology

```
Browser <----- WebRTC (P2P with STUN/TURN) -----> Server
         Video Stream + Data Channel (Input Events)
```

## Configuration

Edit these variables in the scripts:

```python
DISPLAY_NUM = ":99"          # Virtual display number
DISPLAY_WIDTH = 1280         # Display resolution width
DISPLAY_HEIGHT = 900         # Display resolution height
FPS = 30                     # Frames per second (lower = less bandwidth)
```

## Performance Tuning

- **Reduce FPS**: Lower `FPS` value to reduce bandwidth (10-15 FPS is usable)
- **Reduce Resolution**: Lower `DISPLAY_WIDTH` and `DISPLAY_HEIGHT`
- **Network**: Ensure good network connectivity; WebRTC prefers low-latency connections

## Troubleshooting

### Black screen or no video

- Check that Xvfb started: `ps aux | grep Xvfb`
- Check that Electron started: `ps aux | grep electron`
- Check display: `DISPLAY=:99 xdpyinfo`

### Input not working

- Verify xdotool is installed: `which xdotool`
- Check that the data channel is open (see browser console)

### Connection fails

- Check firewall rules
- Try different STUN/TURN servers
- Check browser console for WebRTC errors

## Security Considerations

⚠️ **WARNING**: This streams your full desktop and accepts input commands. Only deploy this in trusted environments or add authentication.

To add basic auth to Modal deployment:

```python
# Add to electron_webrtc_modal.py
from aiohttp import web
import base64

def check_auth(request):
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Basic '):
        raise web.HTTPUnauthorized()
    credentials = base64.b64decode(auth[6:]).decode('utf-8')
    username, password = credentials.split(':', 1)
    if username != 'admin' or password != 'your-secure-password':
        raise web.HTTPUnauthorized()
```

## Browser Compatibility

Tested on:
- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Edge 90+

All modern browsers support WebRTC.

## Limitations

- Audio is not currently streamed (video only)
- Some keyboard shortcuts may be intercepted by the browser
- Network latency affects responsiveness
- Clipboard sharing not implemented

## Future Enhancements

- [ ] Add audio streaming
- [ ] Implement authentication
- [ ] Add clipboard synchronization
- [ ] Support multiple concurrent users
- [ ] Add session recording
- [ ] Implement bandwidth adaptation

## License

Same as the parent project.

## Credits

Built using:
- [aiortc](https://github.com/aiortc/aiortc) - WebRTC implementation
- [Xvfb](https://www.x.org/) - Virtual framebuffer
- [ffmpeg](https://ffmpeg.org/) - Screen capture
- [xdotool](https://github.com/jordansissel/xdotool) - Input simulation

