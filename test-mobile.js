const { app, BrowserWindow } = require('electron');

// iPhone 14 Pro dimensions
const MOBILE_WIDTH = 393;
const MOBILE_HEIGHT = 852;

let mainWindow = null;

function createMobileWindow() {
  mainWindow = new BrowserWindow({
    width: MOBILE_WIDTH,
    height: MOBILE_HEIGHT,
    backgroundColor: '#0f172a',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.setMenu(null);

  // Optional: emulate mobile user agent
  mainWindow.webContents.setUserAgent(
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
  );

  mainWindow.loadURL('https://chatgpt.com/auth/login');

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

app.whenReady().then(() => {
  console.log(`Creating Electron window with mobile dimensions: ${MOBILE_WIDTH}x${MOBILE_HEIGHT}`);
  createMobileWindow();
});

app.on('window-all-closed', () => {
  app.quit();
});

