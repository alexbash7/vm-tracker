// ============ CONFIG ============

const API_BASE = 'https://vm-tracker-api.picreel.xyz';
const TELEMETRY_INTERVAL_MIN = 1;
const OFFLINE_BUFFER_MAX_DAYS = 7;

// ============ STATE ============

let config = null;
let userEmail = null;
let authToken = null;
let isIdle = false;
let retryCount = 0;

// Текущие сессии по вкладкам: { tabId: { url, domain, window_title, start_ts, ... } }
let sessions = {};

// Очередь завершённых сессий для отправки
let closedSessions = [];

// ============ INITIALIZATION ============

chrome.runtime.onInstalled.addListener(() => {
  console.log('[Tracker] Extension installed');
  init();
});

chrome.runtime.onStartup.addListener(() => {
  console.log('[Tracker] Browser started');
  init();
});

async function init() {
  try {
    // 1. Получаем email пользователя из Chrome профиля
    const userInfo = await chrome.identity.getProfileUserInfo({ accountStatus: 'ANY' });
    if (!userInfo.email) {
      console.error('[Tracker] No user email found. Is user signed into Chrome?');
      scheduleRetry(init);
      return;
    }
    userEmail = userInfo.email;
    console.log('[Tracker] User:', userEmail);

    // 2. Получаем OAuth токен
    authToken = await getAuthToken();
    if (!authToken) {
      console.error('[Tracker] Failed to get auth token');
      scheduleRetry(init);
      return;
    }

    // 3. Делаем handshake с сервером
    const handshakeResult = await doHandshake();
    if (!handshakeResult) {
      scheduleRetry(init);
      return;
    }

    // 4. Применяем конфигурацию
    config = handshakeResult;
    console.log('[Tracker] Config received:', config);

    // 5. Проверяем kill switch
    if (config.status === 'banned') {
      console.warn('[Tracker] User is banned. Extension disabled.');
      return;
    }

    // 6. Инжектим куки
    await injectCookies(config.cookies);

    // 7. Устанавливаем правила блокировки
    await setupBlockingRules(config.blocking_rules);

    // 8. Настраиваем idle detection
    chrome.idle.setDetectionInterval(config.idle_threshold_sec);

    // 9. Запускаем таймеры
    setupAlarms();

    // 10. Отправляем буферизованные данные (если есть)
    await flushOfflineBuffer();

    retryCount = 0;
    console.log('[Tracker] Initialization complete');

  } catch (error) {
    console.error('[Tracker] Init error:', error);
    scheduleRetry(init);
  }
}

// ============ AUTH ============

async function getAuthToken() {
  return new Promise((resolve) => {
    chrome.identity.getAuthToken({ interactive: false }, (token) => {
      if (chrome.runtime.lastError) {
        console.error('[Tracker] Auth error:', chrome.runtime.lastError.message);
        // Пробуем интерактивно
        chrome.identity.getAuthToken({ interactive: true }, (token2) => {
          resolve(token2 || null);
        });
      } else {
        resolve(token);
      }
    });
  });
}

async function refreshAuthToken() {
  return new Promise((resolve) => {
    chrome.identity.removeCachedAuthToken({ token: authToken }, async () => {
      authToken = await getAuthToken();
      resolve(authToken);
    });
  });
}

// ============ API CALLS ============

async function doHandshake() {
  try {
    const response = await fetch(`${API_BASE}/api/extension/handshake`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: userEmail,
        auth_token: authToken,
        extension_version: chrome.runtime.getManifest().version
      })
    });

    if (response.status === 401) {
      await refreshAuthToken();
      return null;
    }

    if (!response.ok) {
      console.error('[Tracker] Handshake failed:', response.status);
      return null;
    }

    return await response.json();
  } catch (error) {
    console.error('[Tracker] Handshake network error:', error);
    return null;
  }
}

async function sendTelemetry(events) {
  if (events.length === 0) return true;

  try {
    const response = await fetch(`${API_BASE}/api/extension/telemetry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: userEmail,
        auth_token: authToken,
        events: events
      })
    });

    if (response.status === 401) {
      await refreshAuthToken();
      await saveToOfflineBuffer(events);
      return false;
    }

    if (!response.ok) {
      await saveToOfflineBuffer(events);
      return false;
    }

    console.log('[Tracker] Telemetry sent:', events.length, 'events');
    return true;

  } catch (error) {
    console.error('[Tracker] Telemetry network error:', error);
    await saveToOfflineBuffer(events);
    return false;
  }
}

async function sendScreenshot(dataUrl, timestamp) {
  try {
    // Конвертируем base64 в blob
    const response = await fetch(dataUrl);
    const blob = await response.blob();

    const formData = new FormData();
    formData.append('file', blob, 'screenshot.jpg');
    formData.append('email', userEmail);
    formData.append('auth_token', authToken);
    formData.append('created_at_ts', timestamp.toString());

    const uploadResponse = await fetch(`${API_BASE}/api/extension/screenshot`, {
      method: 'POST',
      body: formData
    });

    if (!uploadResponse.ok) {
      console.error('[Tracker] Screenshot upload failed:', uploadResponse.status);
      return false;
    }

    console.log('[Tracker] Screenshot uploaded');
    return true;

  } catch (error) {
    console.error('[Tracker] Screenshot error:', error);
    return false;
  }
}

// ============ COOKIES INJECTION ============

async function injectCookies(cookies) {
  if (!cookies || cookies.length === 0) return;

  for (const cookie of cookies) {
    try {
      await chrome.cookies.set({
        url: `https://${cookie.domain.replace(/^\./, '')}`,
        domain: cookie.domain,
        name: cookie.name,
        value: cookie.value,
        path: cookie.path || '/',
        secure: cookie.secure !== false,
        expirationDate: cookie.expiration_date || (Date.now() / 1000 + 86400 * 365)
      });
      console.log('[Tracker] Cookie injected:', cookie.domain, cookie.name);
    } catch (error) {
      console.error('[Tracker] Cookie injection failed:', cookie.name, error);
    }
  }
}

// ============ BLOCKING RULES ============

async function setupBlockingRules(rules) {
  if (!rules || rules.length === 0) {
    // Очищаем старые правила
    const existingRules = await chrome.declarativeNetRequest.getDynamicRules();
    const existingIds = existingRules.map(r => r.id);
    if (existingIds.length > 0) {
      await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: existingIds });
    }
    return;
  }

  // Удаляем старые, добавляем новые
  const existingRules = await chrome.declarativeNetRequest.getDynamicRules();
  const existingIds = existingRules.map(r => r.id);

  const newRules = rules.map((rule, index) => ({
    id: index + 1,
    priority: 1,
    action: { type: 'block' },
    condition: {
      regexFilter: rule.pattern,
      resourceTypes: ['main_frame']
    }
  }));

  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: existingIds,
    addRules: newRules
  });

  console.log('[Tracker] Blocking rules applied:', newRules.length);
}

// ============ ALARMS & TIMERS ============

function setupAlarms() {
  // Телеметрия каждую минуту
  chrome.alarms.create('telemetry', { periodInMinutes: TELEMETRY_INTERVAL_MIN });

  // Скриншоты (если включены)
  if (config.screenshot_interval_sec > 0) {
    const screenshotMinutes = config.screenshot_interval_sec / 60;
    chrome.alarms.create('screenshot', { periodInMinutes: screenshotMinutes });
  }

  console.log('[Tracker] Alarms set');
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'telemetry') {
    await processTelemetry();
  } else if (alarm.name === 'screenshot') {
    await captureScreenshot();
  }
});

async function processTelemetry() {
  // Закрываем текущие сессии для снапшота
  const now = Date.now();
  const eventsToSend = [...closedSessions];
  
  // Добавляем снапшоты текущих активных сессий
  for (const [tabId, session] of Object.entries(sessions)) {
    if (session.start_ts) {
      const duration = Math.floor((now - session.start_ts) / 1000);
      if (duration > 0) {
        eventsToSend.push(formatSessionEvent(session, now));
      }
    }
  }

  closedSessions = [];

  // Добавляем из offline буфера
  const buffered = await getOfflineBuffer();
  eventsToSend.push(...buffered);

  if (eventsToSend.length === 0) return;

  const success = await sendTelemetry(eventsToSend);
  if (success) {
    await clearOfflineBuffer();
    retryCount = 0;
  }
}

function formatSessionEvent(session, endTime) {
  const duration = Math.floor((endTime - session.start_ts) / 1000);
  const focusTime = Math.floor(session.focus_time / 1000);

  return {
    url: session.url,
    domain: session.domain,
    window_title: session.window_title,
    start_ts: new Date(session.start_ts).toISOString(),
    duration_sec: duration,
    focus_time_sec: Math.min(focusTime, duration),
    is_idle: session.is_idle || false,
    clicks: session.clicks || 0,
    keypresses: session.keypresses || 0,
    scroll_px: session.scroll_px || 0,
    mouse_px: Math.round(session.mouse_px || 0)
  };
}

// ============ SCREENSHOT ============

let offscreenCreated = false;

async function captureScreenshot() {
  if (!config || config.screenshot_interval_sec === 0) return;

  try {
    // Создаём offscreen document если нужно
    if (!offscreenCreated) {
      await chrome.offscreen.createDocument({
        url: 'offscreen.html',
        reasons: ['BLOBS'],
        justification: 'Screenshot capture'
      });
      offscreenCreated = true;
    }

    // Получаем активную вкладку
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;

    // Делаем скриншот
    const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: 'jpeg', quality: 70 });
    
    // Отправляем на сервер
    await sendScreenshot(dataUrl, Date.now() / 1000);

  } catch (error) {
    console.error('[Tracker] Screenshot capture error:', error);
    offscreenCreated = false;
  }
}

// ============ SESSION MANAGEMENT ============

function startSession(tabId, url, title) {
  const urlObj = new URL(url);
  
  sessions[tabId] = {
    url: url,
    domain: urlObj.hostname,
    window_title: title || urlObj.hostname,
    start_ts: Date.now(),
    focus_time: 0,
    focus_start: document.hasFocus?.() ? Date.now() : null,
    is_idle: isIdle,
    clicks: 0,
    keypresses: 0,
    scroll_px: 0,
    mouse_px: 0
  };

  console.log('[Tracker] Session started:', urlObj.hostname);
}

function closeSession(tabId, reason) {
  const session = sessions[tabId];
  if (!session) return;

  // Финализируем focus time
  if (session.focus_start) {
    session.focus_time += Date.now() - session.focus_start;
    session.focus_start = null;
  }

  const event = formatSessionEvent(session, Date.now());
  
  // Только сохраняем если была какая-то активность или время
  if (event.duration_sec > 0) {
    closedSessions.push(event);
    console.log('[Tracker] Session closed:', session.domain, reason);
  }

  delete sessions[tabId];
}

// ============ TAB EVENTS ============

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    // Пропускаем служебные страницы
    if (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
      return;
    }

    // Если была сессия на другом URL — закрываем
    if (sessions[tabId] && sessions[tabId].url !== tab.url) {
      closeSession(tabId, 'url_changed');
    }

    // Начинаем новую сессию
    if (!sessions[tabId]) {
      startSession(tabId, tab.url, tab.title);
    }
  }
});

chrome.tabs.onActivated.addListener(async (activeInfo) => {
  // Приостанавливаем focus на старых вкладках
  for (const [tabId, session] of Object.entries(sessions)) {
    if (parseInt(tabId) !== activeInfo.tabId && session.focus_start) {
      session.focus_time += Date.now() - session.focus_start;
      session.focus_start = null;
    }
  }

  // Возобновляем focus на активной вкладке
  const session = sessions[activeInfo.tabId];
  if (session && !session.focus_start) {
    session.focus_start = Date.now();
  }

  // Если нет сессии — создаём
  if (!session) {
    try {
      const tab = await chrome.tabs.get(activeInfo.tabId);
      if (tab.url && !tab.url.startsWith('chrome://')) {
        startSession(activeInfo.tabId, tab.url, tab.title);
      }
    } catch (e) {}
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  closeSession(tabId, 'tab_closed');
});

// ============ WINDOW FOCUS ============

chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    // Браузер потерял фокус — приостанавливаем все сессии
    for (const session of Object.values(sessions)) {
      if (session.focus_start) {
        session.focus_time += Date.now() - session.focus_start;
        session.focus_start = null;
      }
    }
  } else {
    // Браузер получил фокус — возобновляем активную вкладку
    const [tab] = await chrome.tabs.query({ active: true, windowId });
    if (tab && sessions[tab.id]) {
      sessions[tab.id].focus_start = Date.now();
    }
  }
});

// ============ IDLE DETECTION ============

chrome.idle.onStateChanged.addListener((state) => {
  console.log('[Tracker] Idle state:', state);
  
  const wasIdle = isIdle;
  isIdle = (state === 'idle' || state === 'locked');

  if (wasIdle !== isIdle) {
    // Закрываем текущие сессии и начинаем новые с другим is_idle статусом
    for (const [tabId, session] of Object.entries(sessions)) {
      closeSession(tabId, isIdle ? 'went_idle' : 'became_active');
      startSession(tabId, session.url, session.window_title);
      sessions[tabId].is_idle = isIdle;
    }
  }
});

// ============ MESSAGES FROM CONTENT SCRIPT ============

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!sender.tab) return;

  const tabId = sender.tab.id;
  const session = sessions[tabId];

  if (!session) return;

  switch (message.type) {
    case 'ACTIVITY':
      session.clicks += message.data.clicks || 0;
      session.keypresses += message.data.keypresses || 0;
      session.scroll_px += message.data.scroll_px || 0;
      session.mouse_px += message.data.mouse_px || 0;
      break;

    case 'VISIBILITY_CHANGE':
      if (message.data.visible && !session.focus_start) {
        session.focus_start = Date.now();
      } else if (!message.data.visible && session.focus_start) {
        session.focus_time += Date.now() - session.focus_start;
        session.focus_start = null;
      }
      break;

    case 'PAGE_UNLOAD':
      closeSession(tabId, 'page_unload');
      break;
  }
});

// ============ OFFLINE BUFFER ============

async function saveToOfflineBuffer(events) {
  const { offlineBuffer = [] } = await chrome.storage.local.get('offlineBuffer');
  
  // Добавляем новые события
  offlineBuffer.push(...events);
  
  // Удаляем старые (старше 7 дней)
  const cutoff = Date.now() - (OFFLINE_BUFFER_MAX_DAYS * 24 * 60 * 60 * 1000);
  const filtered = offlineBuffer.filter(e => new Date(e.start_ts).getTime() > cutoff);
  
  await chrome.storage.local.set({ offlineBuffer: filtered });
  console.log('[Tracker] Saved to offline buffer:', events.length);
}

async function getOfflineBuffer() {
  const { offlineBuffer = [] } = await chrome.storage.local.get('offlineBuffer');
  return offlineBuffer;
}

async function clearOfflineBuffer() {
  await chrome.storage.local.set({ offlineBuffer: [] });
}

async function flushOfflineBuffer() {
  const buffered = await getOfflineBuffer();
  if (buffered.length > 0) {
    console.log('[Tracker] Flushing offline buffer:', buffered.length);
    const success = await sendTelemetry(buffered);
    if (success) {
      await clearOfflineBuffer();
    }
  }
}

// ============ RETRY LOGIC ============

const RETRY_INTERVALS = [30000, 60000, 300000, 600000];

function scheduleRetry(fn) {
  const delay = RETRY_INTERVALS[Math.min(retryCount, RETRY_INTERVALS.length - 1)];
  retryCount++;
  console.log(`[Tracker] Retrying in ${delay / 1000}s (attempt ${retryCount})`);
  setTimeout(fn, delay);
}