/**
 * Type definitions for ChatGPT Login embeddable component
 */

export interface ChatGPTCredentials {
  email: string;
  accessToken: string;
  sessionToken?: string;
  userId?: string;
  timestamp: number;
}

export interface CredentialMessage {
  type: 'chatgpt-credentials';
  credentials: ChatGPTCredentials;
}

export interface EmbedConfig {
  apiKey: string;
  embedUrl: string;
  accentColor?: string;
  logoUrl?: string;
  onCredentials: (credentials: ChatGPTCredentials) => void;
  onError?: (error: Error) => void;
}

