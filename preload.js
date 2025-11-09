const { contextBridge, ipcRenderer } = require('electron');

window.addEventListener('DOMContentLoaded', () => {
  // We can't directly access the DOM of the remote page from the preload script
  // in the same way we would with a local file due to security restrictions.
  // Instead, we have to rely on events from the webContents.
  // The logic for detecting navigation is now in main.js
  // This preload script is now primarily for exposing node APIs to the renderer
  // in a secure way, if needed.

  console.log('Preload script loaded.');
});

contextBridge.exposeInMainWorld('progressAPI', {
  onStageUpdate: (callback) => ipcRenderer.on('stage-update', (event, ...args) => callback(...args)),
  onConversationData: (callback) => ipcRenderer.on('conversation-data', (event, ...args) => callback(...args)),
  onConversationProgress: (callback) => ipcRenderer.on('conversation-progress', (event, ...args) => callback(...args)),
  onDetailProgress: (callback) => ipcRenderer.on('detail-progress', (event, ...args) => callback(...args)),
  onDetailFetchProgress: (callback) => ipcRenderer.on('detail-fetch-progress', (event, ...args) => callback(...args)),
  exportSelected: (ids) => ipcRenderer.send('export-selected', ids),
  getConversationContent: (id) => ipcRenderer.invoke('get-conversation-content', id),
});
