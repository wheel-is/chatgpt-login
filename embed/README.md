# ChatGPT Login Embeddable Component

An embeddable iframe component that allows third-party websites to securely capture ChatGPT login credentials through a WebRTC-streamed Electron application.

## Table of Contents

- [Quick Start](#quick-start)
- [API Key Management](#api-key-management)
- [Integration Methods](#integration-methods)
- [Credential Response](#credential-response)
- [Security](#security)
- [Customization](#customization)
- [TypeScript Example](#typescript-example)

## Quick Start

### 1. Get an API Key

Generate an API key by making a POST request to your server:

```bash
curl -X POST http://64.23.163.23:8080/api/keys
```

Response:
```json
{
  "api_key": "sk_abc123...",
  "created_at": 1699999999.123
}
```

Save this API key - you'll need it for all embed requests.

### 2. Embed the Component

Add this iframe to your website:

```html
<iframe 
    src="http://64.23.163.23:8080/embed?api_key=YOUR_API_KEY"
    width="100%"
    height="700px"
    allow="clipboard-read; clipboard-write"
    style="border: none; border-radius: 8px;">
</iframe>
```

### 3. Listen for Credentials

Add JavaScript to receive the credentials:

```javascript
window.addEventListener('message', (event) => {
    // Validate origin in production
    // if (event.origin !== 'http://64.23.163.23:8080') return;
    
    if (event.data.type === 'chatgpt-credentials') {
        const credentials = event.data.credentials;
        
        console.log('Email:', credentials.email);
        console.log('Access Token:', credentials.accessToken);
        
        // Use credentials to make ChatGPT API requests
        authenticateUser(credentials);
    }
});
```

## API Key Management

### Generate a New Key

**Endpoint:** `POST /api/keys`

```bash
curl -X POST http://64.23.163.23:8080/api/keys
```

**Response:**
```json
{
  "api_key": "sk_randomstring...",
  "created_at": 1699999999.123
}
```

### List Active Keys

**Endpoint:** `GET /api/keys`

```bash
curl http://64.23.163.23:8080/api/keys
```

**Response:**
```json
{
  "keys": [
    {
      "key": "sk_abc123...",
      "created_at": 1699999999.123,
      "usage_last_hour": 5
    }
  ]
}
```

### Rate Limits

- **10 logins per hour** per API key
- Automatically enforced
- Returns `401 Unauthorized` if exceeded

## Integration Methods

### Method 1: Simple iframe (Recommended)

```html
<!DOCTYPE html>
<html>
<body>
    <div id="login-container">
        <iframe 
            src="http://64.23.163.23:8080/embed?api_key=YOUR_API_KEY"
            width="100%"
            height="700px"
            allow="clipboard-read; clipboard-write">
        </iframe>
    </div>

    <script>
        window.addEventListener('message', (event) => {
            if (event.data.type === 'chatgpt-credentials') {
                console.log('Login successful!', event.data.credentials);
                // Handle credentials
            }
        });
    </script>
</body>
</html>
```

### Method 2: TypeScript SDK

See [`example-integration/`](./example-integration/) for a complete TypeScript implementation with:
- Type-safe credential handling
- Error handling
- Reusable component class
- Vite-based development setup

## Credential Response

When login is successful, the iframe sends a `postMessage` with this structure:

```typescript
interface CredentialMessage {
  type: 'chatgpt-credentials';
  credentials: {
    email: string;
    accessToken: string;
    sessionToken?: string;
    userId?: string;
    timestamp: number;
  };
}
```

**Example payload:**
```json
{
  "type": "chatgpt-credentials",
  "credentials": {
    "email": "user@example.com",
    "accessToken": "eyJhbGciOiJSUzI1NiIs...",
    "sessionToken": "sess_abc123...",
    "userId": "user-abc123",
    "timestamp": 1699999999123
  }
}
```

## Security

### API Key Security

- Store API keys securely (environment variables, secret managers)
- Never commit API keys to version control
- Rotate keys regularly
- Each key is tracked for rate limiting

### PostMessage Security

**Always validate the message origin:**

```javascript
window.addEventListener('message', (event) => {
    // Validate origin
    if (event.origin !== 'http://64.23.163.23:8080') {
        console.warn('Ignored message from untrusted origin:', event.origin);
        return;
    }
    
    if (event.data.type === 'chatgpt-credentials') {
        // Safe to use credentials
        handleCredentials(event.data.credentials);
    }
});
```

### Session Management

- Sessions automatically timeout after **5 minutes**
- Electron process restarts on each disconnect for fresh sessions
- Rate limit: **10 logins per hour per API key**

### HTTPS Recommendations

For production:
1. Use HTTPS for the embed server
2. Update iframe `src` to use `https://`
3. Configure proper CSP headers
4. Validate referring domains

## Customization

The embed endpoint accepts query parameters for branding:

```html
<iframe src="http://64.23.163.23:8080/embed?
    api_key=YOUR_KEY&
    accent_color=%23ff6b6b&
    logo_url=https://yoursite.com/logo.png">
</iframe>
```

**Parameters:**

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `api_key` | string | Required API key | - |
| `accent_color` | string | Hex color for UI elements | `#10a37f` |
| `logo_url` | string | URL to your logo image | None |

## TypeScript Example

See the complete TypeScript example in [`example-integration/`](./example-integration/):

```bash
cd example-integration
npm install
npm run dev
```

This will start a development server at `http://localhost:3000` with a fully functional demo.

### Key Files

- **[`src/types.ts`](./example-integration/src/types.ts)** - TypeScript type definitions
- **[`src/main.ts`](./example-integration/src/main.ts)** - Reusable `ChatGPTLoginEmbed` class
- **[`index.html`](./example-integration/index.html)** - Demo integration example

## Testing

### Standalone Test Page

Open [`embed.html`](./embed.html) directly in your browser to test the embed without setting up the TypeScript example.

Just update the `api_key` in the iframe src attribute:

```html
<iframe 
    src="http://64.23.163.23:8080/embed?api_key=YOUR_API_KEY"
    ...>
</iframe>
```

## Troubleshooting

### "Invalid API key" error

- Check that you're using a valid API key from `/api/keys`
- Ensure the key is passed in the URL: `?api_key=sk_...`

### "Rate limit exceeded" error

- Each API key is limited to 10 logins/hour
- Generate a new API key or wait an hour

### No postMessage received

- Check browser console for CORS errors
- Verify iframe has `allow="clipboard-read; clipboard-write"`
- Ensure you're listening for `message` events on `window`

### Connection stays on "Connecting..."

- Check that WebRTC ports (3478, 5349) are accessible
- Verify TURN server is running: `docker logs -f chatgpt-login-electron-webrtc-1`
- Try refreshing the page

### Black screen

- Check Docker logs: `docker logs chatgpt-login-electron-webrtc-1`
- Verify Electron and Xvfb started successfully
- Ensure display resolution matches configuration

## Production Deployment

### Environment Variables

Set these on your server:

```bash
export SERVER_HOST=0.0.0.0
export SERVER_PORT=8080
export TURN_EXTERNAL_IP=your.server.ip
```

### HTTPS Setup

Use Nginx as a reverse proxy:

```nginx
server {
    listen 443 ssl;
    server_name login.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Docker Compose Production

Update `docker-compose.yml` with proper resource limits:

```yaml
services:
  electron-webrtc:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
    restart: unless-stopped
```

## API Reference

### Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/` | GET | Full UI with controls | Optional |
| `/embed` | GET | Minimal iframe embed | Required |
| `/offer` | POST | WebRTC signaling | Required |
| `/api/keys` | POST | Generate API key | Admin |
| `/api/keys` | GET | List API keys | Admin |
| `/restart-electron` | POST | Restart Electron | Internal |

### Query Parameters

**`/embed` endpoint:**

- `api_key` (required): Your API key
- `accent_color` (optional): Hex color code (URL encoded)
- `logo_url` (optional): URL to logo image

## Support

For issues or questions:
- GitHub: https://github.com/wheel-is/chatgpt-login
- Email: will@penumbraholdings.com

## License

See repository LICENSE file.

