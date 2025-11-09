const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('progressAPI', {
  onStageUpdate: (callback) => ipcRenderer.on('stage-update', (_, data) => callback(data)),
  onConversationData: (callback) => ipcRenderer.on('conversation-data', (_, data) => callback(data)),
  onConversationProgress: (callback) => ipcRenderer.on('conversation-progress', (_, data) => callback(data)),
  onDetailProgress: (callback) => ipcRenderer.on('detail-progress', (_, data) => callback(data)),
  exportSelected: (conversations) => ipcRenderer.send('export-selected', conversations),
  getConversationContent: (conversationId) => ipcRenderer.invoke('get-conversation-content', conversationId),
});
