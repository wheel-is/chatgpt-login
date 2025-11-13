/**
 * ChatGPT Login Widget
 * Embeddable component that automatically adapts to container dimensions
 * 
 * Usage:
 * 
 * // Auto mode - detects container size
 * <div id="chatgpt-login-widget" style="width: 100%; height: 600px;"></div>
 * <script src="chatgpt-login-widget.js"></script>
 * <script>
 *   ChatGPTLoginWidget.mount('#chatgpt-login-widget', {
 *     serverUrl: 'http://64.23.163.23:8080',
 *     onCredentials: (credentials) => {
 *       console.log('Received credentials:', credentials);
 *     }
 *   });
 * </script>
 * 
 * // Manual dimensions (e.g. iPhone)
 * ChatGPTLoginWidget.mount('#chatgpt-login-widget', {
 *   serverUrl: 'http://64.23.163.23:8080',
 *   width: 393,  // iPhone width
 *   height: 852, // iPhone height
 *   onCredentials: (credentials) => { ... }
 * });
 */

(function() {
  'use strict';

  const ChatGPTLoginWidget = {
    /**
     * Mount the login widget into a container
     * @param {string} containerSelector - CSS selector for container element
     * @param {Object} options - Configuration options
     * @param {string} options.serverUrl - WebRTC server URL (e.g. 'http://64.23.163.23:8080')
     * @param {number} [options.width] - Manual width (optional, auto-detected if not provided)
     * @param {number} [options.height] - Manual height (optional, auto-detected if not provided)
     * @param {Function} [options.onCredentials] - Callback when credentials are received
     */
    mount: function(containerSelector, options = {}) {
      const container = document.querySelector(containerSelector);
      if (!container) {
        throw new Error(`Container not found: ${containerSelector}`);
      }

      const serverUrl = options.serverUrl;
      if (!serverUrl) {
        throw new Error('serverUrl is required');
      }

      // Determine dimensions
      let width, height;
      
      if (options.width && options.height) {
        // Manual mode
        width = options.width;
        height = options.height;
        console.log(`ChatGPT Login Widget: Using manual dimensions ${width}x${height}`);
      } else {
        // Auto mode - use container dimensions
        const rect = container.getBoundingClientRect();
        width = Math.floor(rect.width);
        height = Math.floor(rect.height);
        
        // Ensure minimum dimensions
        width = Math.max(width, 320);
        height = Math.max(height, 480);
        console.log(`ChatGPT Login Widget: Auto-detected dimensions ${width}x${height}`);
      }

      // Create iframe with dimension parameters
      const iframe = document.createElement('iframe');
      iframe.src = `${serverUrl}/embed?width=${width}&height=${height}`;
      iframe.style.width = '100%';
      iframe.style.height = '100%';
      iframe.style.border = 'none';
      iframe.allow = 'clipboard-read; clipboard-write';
      
      // Listen for credentials from iframe
      const messageHandler = (event) => {
        // Verify message is from our server
        if (!event.origin.includes(new URL(serverUrl).hostname)) {
          return;
        }

        if (event.data && event.data.type === 'chatgpt-credentials') {
          console.log('ChatGPT Login Widget: Credentials received');
          if (options.onCredentials) {
            options.onCredentials(event.data.credentials);
          }
        }
      };

      window.addEventListener('message', messageHandler);

      // Clear container and mount iframe
      container.innerHTML = '';
      container.appendChild(iframe);

      return {
        iframe,
        destroy: () => {
          window.removeEventListener('message', messageHandler);
          if (iframe.parentNode) {
            iframe.parentNode.removeChild(iframe);
          }
        }
      };
    }
  };

  // Export for browser
  if (typeof window !== 'undefined') {
    window.ChatGPTLoginWidget = ChatGPTLoginWidget;
  }

  // Export for module systems
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChatGPTLoginWidget;
  }
})();

