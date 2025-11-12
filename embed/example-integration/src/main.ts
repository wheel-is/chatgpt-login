import { ChatGPTCredentials, CredentialMessage, EmbedConfig } from './types';

/**
 * ChatGPT Login Embeddable Component
 * 
 * Usage:
 * ```typescript
 * import { ChatGPTLoginEmbed } from './main';
 * 
 * const embed = new ChatGPTLoginEmbed({
 *   apiKey: 'sk_your_api_key_here',
 *   embedUrl: 'http://64.23.163.23:8080/embed',
 *   onCredentials: (creds) => {
 *     console.log('Received credentials:', creds);
 *   }
 * });
 * 
 * document.getElementById('login-container').appendChild(embed.iframe);
 * ```
 */
export class ChatGPTLoginEmbed {
  private iframe: HTMLIFrameElement;
  private config: EmbedConfig;
  private messageListener: ((event: MessageEvent) => void) | null = null;

  constructor(config: EmbedConfig) {
    this.config = config;
    this.iframe = this.createIframe();
    this.setupMessageListener();
  }

  private createIframe(): HTMLIFrameElement {
    const iframe = document.createElement('iframe');
    
    // Build URL with query parameters
    const url = new URL(this.config.embedUrl);
    url.searchParams.set('api_key', this.config.apiKey);
    if (this.config.accentColor) {
      url.searchParams.set('accent_color', this.config.accentColor);
    }
    if (this.config.logoUrl) {
      url.searchParams.set('logo_url', this.config.logoUrl);
    }

    iframe.src = url.toString();
    iframe.style.width = '100%';
    iframe.style.height = '600px';
    iframe.style.border = 'none';
    iframe.style.borderRadius = '8px';
    iframe.allow = 'clipboard-read; clipboard-write';

    return iframe;
  }

  private setupMessageListener(): void {
    this.messageListener = (event: MessageEvent) => {
      // In production, validate event.origin
      try {
        const data = event.data as CredentialMessage;
        
        if (data.type === 'chatgpt-credentials') {
          console.log('[ChatGPT Login] Credentials received');
          this.config.onCredentials(data.credentials);
          
          // Auto-cleanup after credentials received
          this.destroy();
        }
      } catch (error) {
        if (this.config.onError) {
          this.config.onError(error as Error);
        }
      }
    };

    window.addEventListener('message', this.messageListener);
  }

  public destroy(): void {
    if (this.messageListener) {
      window.removeEventListener('message', this.messageListener);
      this.messageListener = null;
    }
    
    if (this.iframe.parentNode) {
      this.iframe.parentNode.removeChild(this.iframe);
    }
  }

  public getIframe(): HTMLIFrameElement {
    return this.iframe;
  }
}

// Demo application
class DemoApp {
  private container: HTMLElement;
  private credentialsDisplay: HTMLElement;

  constructor() {
    this.container = document.getElementById('app')!;
    this.credentialsDisplay = document.getElementById('credentials')!;
    this.setupUI();
  }

  private setupUI(): void {
    const button = document.createElement('button');
    button.textContent = 'Start ChatGPT Login';
    button.className = 'start-button';
    button.onclick = () => this.startLogin();

    const title = document.createElement('h1');
    title.textContent = 'ChatGPT Login Embed Demo';
    
    const description = document.createElement('p');
    description.textContent = 'Click the button below to start the embedded login flow.';
    description.style.marginBottom = '20px';

    this.container.innerHTML = '';
    this.container.appendChild(title);
    this.container.appendChild(description);
    this.container.appendChild(button);
  }

  private startLogin(): void {
    // Clear container
    this.container.innerHTML = '<h2>Complete login in the frame below:</h2>';
    
    const iframeContainer = document.createElement('div');
    iframeContainer.className = 'iframe-container';

    // Create embed instance
    const embed = new ChatGPTLoginEmbed({
      apiKey: 'sk_demo_key',  // Replace with your actual API key
      embedUrl: 'http://64.23.163.23:8080/embed',
      accentColor: '#10a37f',
      onCredentials: (credentials) => {
        this.displayCredentials(credentials);
      },
      onError: (error) => {
        console.error('Login error:', error);
        alert('Login failed: ' + error.message);
      }
    });

    iframeContainer.appendChild(embed.getIframe());
    this.container.appendChild(iframeContainer);
  }

  private displayCredentials(credentials: ChatGPTCredentials): void {
    this.credentialsDisplay.style.display = 'block';
    this.credentialsDisplay.innerHTML = `
      <h3>✓ Login Successful!</h3>
      <div class="credential-item">
        <strong>Email:</strong> ${credentials.email}
      </div>
      <div class="credential-item">
        <strong>Access Token:</strong> <code>${credentials.accessToken.substring(0, 20)}...</code>
      </div>
      <div class="credential-item">
        <strong>User ID:</strong> ${credentials.userId || 'N/A'}
      </div>
      <div class="credential-item">
        <strong>Timestamp:</strong> ${new Date(credentials.timestamp).toLocaleString()}
      </div>
      <button onclick="location.reload()" class="restart-button">Try Again</button>
    `;
  }
}

// Initialize demo app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => new DemoApp());
} else {
  new DemoApp();
}

