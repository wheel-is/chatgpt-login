const { app, BrowserWindow, session, ipcMain } = require('electron');
const fs = require('fs/promises');
const path = require('path');

const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
const SESSION_ENDPOINT = 'https://chatgpt.com/api/auth/session';
const CONVERSATIONS_ENDPOINT = 'https://chatgpt.com/backend-api/conversations';
const CONVERSATION_DETAIL_ENDPOINT = 'https://chatgpt.com/backend-api/conversation';
const MODAL_PRICING_URL = 'https://penumbra--conversation-pricing-price-conversations.modal.run';
const OUTPUT_PATH = path.join(__dirname, 'conversation_history.json');
const CREDENTIALS_PATH = path.join(__dirname, 'session_credentials.json');
const CONVERSATION_PAGE_SIZE = 100;
const DETAIL_CONCURRENCY = 6;

let mainWindow = null;
let hasPulledHistory = false;
let isProgressView = false;
let progressReady = false;
const pendingProgressMessages = [];

let currentSession = null;
let currentAccessToken = null;
let currentCookieHeader = null;
let conversationLookup = new Map();

function queueProgressMessage(channel, payload) {
  pendingProgressMessages.push({ channel, payload });
  flushProgressMessages();
}

function flushProgressMessages() {
  if (!isProgressView || !progressReady || !mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  while (pendingProgressMessages.length > 0) {
    const { channel, payload } = pendingProgressMessages.shift();
    mainWindow.webContents.send(channel, payload);
  }
}

function sendToProgress(channel, payload) {
  if (!isProgressView || !progressReady || !mainWindow || mainWindow.isDestroyed()) {
    queueProgressMessage(channel, payload);
    return;
  }

  mainWindow.webContents.send(channel, payload);
}

function updateStage(stage, message) {
  sendToProgress('stage-update', { stage, message });
}

function logStatus(message) {
  console.log(message);
  sendToProgress('status-log', { message, timestamp: new Date().toISOString() });
}

function updateConversationProgress(completed) {
  sendToProgress('conversation-progress', { completed });
}

function updateDetailProgress(completed, total) {
  sendToProgress('detail-progress', { completed, total });
}

async function buildCookieHeader() {
  const cookies = await session.defaultSession.cookies.get({});

  const relevantCookies = cookies
    .filter(({ domain }) => domain.includes('chatgpt.com') || domain.includes('openai.com'))
    .map(({ name, value }) => `${name}=${value}`);

  return relevantCookies.join('; ');
}

async function fetchAccessToken(cookieHeader) {
  const response = await fetch(SESSION_ENDPOINT, {
    headers: {
      Accept: 'application/json',
      Cookie: cookieHeader,
      'User-Agent': USER_AGENT,
    },
  });

  const bodyText = await response.text();
  logStatus(`Session endpoint status: ${response.status}`);
  logStatus(`Session endpoint body: ${bodyText.slice(0, 600)}${bodyText.length > 600 ? '…' : ''}`);

  if (!response.ok) {
    throw new Error(`Session endpoint request failed: ${response.status} ${response.statusText}`);
  }

  try {
    const data = JSON.parse(bodyText);
    return { accessToken: data?.accessToken ?? null, sessionBody: data };
  } catch (error) {
    throw new Error(`Failed to parse session response JSON: ${error.message}`);
  }
}

async function fetchConversationHistory(accessToken, cookieHeader, offset, limit) {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    order: 'updated',
    is_archived: 'false',
    is_starred: 'false',
  });

  const response = await fetch(`${CONVERSATIONS_ENDPOINT}?${params.toString()}`, {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
      Cookie: cookieHeader,
      Referer: 'https://chatgpt.com/',
      'User-Agent': USER_AGENT,
    },
  });

  const bodyText = await response.text();
  logStatus(`Conversation history status: ${response.status}`);
  logStatus(`Conversation history body (offset=${offset}): ${bodyText.slice(0, 800)}${bodyText.length > 800 ? '…' : ''}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch conversations: ${response.status} ${response.statusText}`);
  }

  try {
    return JSON.parse(bodyText);
  } catch (error) {
    throw new Error(`Failed to parse conversation history JSON: ${error.message}`);
  }
}

async function fetchAllConversations(accessToken, cookieHeader) {
  let offset = 0;
  const items = [];
  
  updateConversationProgress(0);

  while (true) {
    const page = await fetchConversationHistory(accessToken, cookieHeader, offset, CONVERSATION_PAGE_SIZE);
    if (!Array.isArray(page.items) || page.items.length === 0) {
      break;
    }
    items.push(...page.items);
    updateConversationProgress(items.length);
    const pageLimit = page.limit ?? CONVERSATION_PAGE_SIZE;
    if (pageLimit <= 0) break;
    offset += pageLimit;
  }
  logStatus(`Found ${items.length} conversations.`);
  return { items };
}

async function persistConversationHistory(history) {
  const serialized = JSON.stringify(history, null, 2);
  await fs.writeFile(OUTPUT_PATH, serialized, 'utf8');
}

async function priceConversations(conversations) {
  logStatus(`Pricing ${conversations.length} conversations via Modal...`);

  try {
    const response = await fetch(MODAL_PRICING_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
      },
      body: JSON.stringify(conversations),
    });

    const responseText = await response.text();
    logStatus(`Pricing API status: ${response.status}`);

    if (!response.ok) {
      logStatus(`Pricing API error response: ${responseText}`);
      throw new Error(`Pricing API failed: ${response.status} ${response.statusText}`);
    }

    const pricingData = JSON.parse(responseText);
    logStatus(`Successfully priced ${Object.keys(pricingData).length} conversations`);
    return pricingData;
  } catch (error) {
    logStatus(`Pricing failed: ${error.message}`);
    // Return empty pricing data if Modal fails, so the app can still continue
    return {};
  }
}

async function fetchConversationDetails(conversationId, accessToken, cookieHeader) {
  const response = await fetch(`${CONVERSATION_DETAIL_ENDPOINT}/${conversationId}`, {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
      Cookie: cookieHeader,
      Referer: `https://chatgpt.com/c/${conversationId}`,
      'User-Agent': USER_AGENT,
    },
  });

  const bodyText = await response.text();
  logStatus(`Conversation detail status (${conversationId}): ${response.status}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch conversation ${conversationId}: ${response.status} ${response.statusText}`);
  }

  try {
    return JSON.parse(bodyText);
  } catch (error) {
    throw new Error(`Failed to parse conversation ${conversationId} JSON: ${error.message}`);
  }
}

async function persistConversationDetails({ conversations, session }) {
  const userEmail = session?.user?.email;
  if (!userEmail) {
    throw new Error('Could not determine user email from session.');
  }

  // Sanitize email for filesystem (replace @ and other potentially problematic chars)
  const sanitizedEmail = userEmail.replace(/[@\.\+\[\]\{\}\(\)\s]/g, '_');
  const userDir = path.join(__dirname, sanitizedEmail);
  await fs.mkdir(userDir, { recursive: true });
  logStatus(`Saving ${conversations.length} conversation details to ${userDir}...`);

  let completed = 0;
  const total = conversations.length;

  for (const conversation of conversations) {
    try {
      const conversationId = conversation.id || conversation.conversation_id;
      if (!conversationId) {
        logStatus('Skipping conversation with no ID.');
        continue;
      }
      const filePath = path.join(userDir, `${conversationId}.json`);
      await fs.writeFile(filePath, JSON.stringify(conversation, null, 2), 'utf8');
      
      completed++;
      updateDetailProgress(completed, total);

    } catch (error) {
      logStatus(`Failed to save conversation ${conversation.id || conversation.conversation_id}: ${error.message}`);
    }
  }

  return userDir;
}

async function persistCredentials(credentials) {
  const serialized = JSON.stringify(credentials, null, 2);
  await fs.writeFile(CREDENTIALS_PATH, serialized, 'utf8');
}

function createMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    return mainWindow;
  }

  mainWindow = new BrowserWindow({
    width: 1100,
    height: 900,
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'progress-preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  isProgressView = false;
  progressReady = false;
  pendingProgressMessages.length = 0;

  mainWindow.loadURL('https://chat.openai.com/auth/login');
  attachLoginListeners(mainWindow);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

function attachLoginListeners(window) {
  const { webContents } = window;

  const handleNavigation = async (event, url) => {
    logStatus(`Navigated to: ${url}`);

    if (hasPulledHistory) {
      return;
    }

    if (
      url.startsWith('https://chat.openai.com/c/') ||
      url.startsWith('https://chatgpt.com/c/') ||
      /https:\/\/chatgpt\.com\/?$/.test(url)
    ) {
      hasPulledHistory = true;
      webContents.removeListener('did-navigate', handleNavigation);
      webContents.removeListener('did-navigate-in-page', handleNavigation);

      try {
        await enterProgressView();
        await handleSuccessfulLogin();
      } catch (error) {
        logStatus(`Export failed: ${error.message}`);
        updateStage('error', `Export failed: ${error.message}`);
      }
    }
  };

  webContents.on('did-navigate', handleNavigation);
  webContents.on('did-navigate-in-page', handleNavigation);
}

function enterProgressView() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    throw new Error('Main window unavailable');
  }

  isProgressView = true;
  progressReady = false;

  return new Promise((resolve) => {
    mainWindow.webContents.once('did-finish-load', () => {
      progressReady = true;
      flushProgressMessages();
      resolve();
    });

    mainWindow.loadFile('progress.html');
  });
}

async function handleSuccessfulLogin() {
  updateStage('session', 'Capturing session...');

  const cookieHeader = await buildCookieHeader();
  const { accessToken, sessionBody } = await fetchAccessToken(cookieHeader);
  await persistCredentials({
    accessToken,
    cookies: cookieHeader,
    session: sessionBody,
    savedAt: new Date().toISOString(),
  });

  currentAccessToken = accessToken;
  currentCookieHeader = cookieHeader;
  currentSession = sessionBody;

  updateStage('conversation-list', 'Collecting conversation IDs...');
  const history = await fetchAllConversations(accessToken, cookieHeader);
  await persistConversationHistory(history);

  // Fetch full details for all conversations before pricing
  updateStage('fetching-details', `Fetching details for ${history.items.length} conversations...`);
  
  const conversationDetails = [];
  const queue = [...history.items];
  let completedFetches = 0;
  
  const worker = async () => {
    while (queue.length > 0) {
      const item = queue.shift();
      if (item) {
        try {
          const detail = await fetchConversationDetails(item.id, accessToken, cookieHeader);
          conversationDetails.push(detail);
        } catch (error) {
          logStatus(`Failed to fetch detail for ${item.id}: ${error.message}`);
        }
        completedFetches++;
        if (mainWindow) {
            mainWindow.webContents.send('detail-fetch-progress', { completed: completedFetches, total: history.items.length });
        }
      }
    }
  };

  const workers = Array(DETAIL_CONCURRENCY).fill(null).map(worker);
  await Promise.all(workers);

  // Price the full conversations
  updateStage('pricing', 'Analyzing conversations for pricing and duplicates...');
  const pricingData = await priceConversations(conversationDetails);

  const conversationsWithPricing = conversationDetails.map(item => {
    const pricingInfo = pricingData[item.conversation_id] || {};
    return {
      ...item,
      id: item.conversation_id,
      title: item.title || 'Untitled Conversation',
      create_time: pricingInfo.log?.create_time || item.create_time,
      update_time: pricingInfo.log?.update_time || item.update_time,
      pricing: pricingInfo,
    };
  });

  conversationLookup = new Map(conversationsWithPricing.map((item) => [item.id, item]));

  // Automatically save all conversations to user folder
  updateStage('conversation-details', `Saving ${conversationsWithPricing.length} conversations to user folder...`);
  updateDetailProgress(0, conversationsWithPricing.length);

  try {
    const detailsDir = await persistConversationDetails({
      conversations: conversationsWithPricing,
      session: sessionBody,
    });

    logStatus(`All conversation details saved under ${detailsDir}`);
    updateStage('complete', 'All conversations have been downloaded. You can now close this window.');
  } catch (error) {
    logStatus(`Detail export failed: ${error.message}`);
    updateStage('error', `Detail export failed: ${error.message}`);
  }
}

app.whenReady().then(async () => {
  logStatus('Clearing Electron session storage for a cold login...');
  try {
    await session.defaultSession.clearStorageData();
    logStatus('Session storage cleared.');
  } catch (error) {
    logStatus(`Failed to clear session storage: ${error.message}`);
  }

  ipcMain.handle('get-conversation-content', async (event, conversationId) => {
    if (!currentAccessToken || !currentCookieHeader) {
      throw new Error('Not authenticated yet; please log in first.');
    }
    try {
      const details = await fetchConversationDetails(
        conversationId,
        currentAccessToken,
        currentCookieHeader
      );
      return details;
    } catch (error) {
      logStatus(`Failed to fetch conversation ${conversationId}: ${error.message}`);
      throw error;
    }
  });

  hasPulledHistory = false;
  createMainWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (!mainWindow) {
    hasPulledHistory = false;
    createMainWindow();
  }
});
