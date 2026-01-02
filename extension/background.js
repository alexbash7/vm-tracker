// ============ CONFIG ============

const API_BASE = 'https://vm-tracker-api.picreel.xyz';
const TELEMETRY_INTERVAL_MIN = 1;
const OFFLINE_BUFFER_MAX_DAYS = 7;
const MIN_SESSION_DURATION_SEC = 3; // Минимальная длительность сессии

// ============ STATE ============

let config = null;
let userEmail = null;
let authToken = null;
let isIdle = false;
let retryCount = 0;

// Текущая активная сессия (только одна)
let currentSession = null;
let currentTabId = null;

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

    // 11. Начинаем трекать текущую активную вкладку
    await startTrackingActiveTab();

    retryCount = 0;
    console.log('[Tracker] Initialization complete');

    await loadUpworkFilter();

    // Сохраняем autofill конфиг
    if (config.autofill_config) {
        await chrome.storage.local.set({ autofillConfig: config.autofill_config });
        console.log('[Tracker] Autofill config saved');
    }


  } catch (error) {
    console.error('[Tracker] Init error:', error);
    scheduleRetry(init);
  }
}

async function startTrackingActiveTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url && !tab.url.startsWith('chrome://') && !tab.url.startsWith('chrome-extension://')) {
      await startSession(tab.id, tab.url, tab.title);
    }
  } catch (e) {
    console.error('[Tracker] Failed to get active tab:', e);
  }
}

// ============ AUTH ============

async function getAuthToken() {
  return new Promise((resolve) => {
    chrome.identity.getAuthToken({ interactive: false }, (token) => {
      if (chrome.runtime.lastError) {
        console.error('[Tracker] Auth error:', chrome.runtime.lastError.message);
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
  if (!events || events.length === 0) return true;
  
  // Проверяем что есть credentials
  if (!userEmail || !authToken) {
    console.log('[Tracker] Telemetry delayed - no credentials');
    await saveToOfflineBuffer(events);
    return false;
  }

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
  
  const injectedIds = [];
  
  for (const cookie of cookies) {
    try {
      await chrome.cookies.set({
        url: `https://${cookie.domain.replace(/^\./, '')}`,
        domain: cookie.domain,
        name: cookie.name,
        value: cookie.value,
        path: cookie.path || '/',
        secure: cookie.secure !== false,
        expirationDate: cookie.expiration_date || undefined
      });
      
      injectedIds.push(cookie.id);
      console.log('[Tracker] Cookie injected:', cookie.domain, cookie.name);
    } catch (e) {
      console.error('[Tracker] Cookie injection failed:', e);
    }
  }
  
  // Сообщаем серверу что куки инжектированы
  if (injectedIds.length > 0) {
    try {
      await fetch(`${API_BASE}/api/extension/cookies-injected`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: userEmail,
          cookie_ids: injectedIds
        })
      });
    } catch (e) {
      console.error('[Tracker] Failed to mark cookies as injected:', e);
    }
  }
}

// ============ BLOCKING RULES ============

let blockPatterns = [];
let allowPatterns = [];

async function setupBlockingRules(rules) {
  if (!rules || rules.length === 0) {
    blockPatterns = [];
    allowPatterns = [];
    console.log('[Tracker] No blocking rules');
    return;
  }

  blockPatterns = rules.filter(r => r.action === 'block').map(r => r.pattern);
  allowPatterns = rules.filter(r => r.action === 'allow').map(r => r.pattern);
  
  console.log('[Tracker] Blocking rules applied - block:', blockPatterns.length, 'allow:', allowPatterns.length);
}


// FIX: Переписана логика - сначала проверяем ВСЕ allow паттерны, потом ВСЕ block паттерны
function isUrlBlocked(url) {
  if (!url) return false;
  
  // Skip chrome and extension pages
  if (url.startsWith('chrome://') || url.startsWith('chrome-extension://')) return false;
  
  // Если правила не загружены — не блокируем
  if (!allowPatterns || !blockPatterns) return false;
  
  // Extract domain from URL
  let urlDomain;
  try {
    urlDomain = new URL(url).hostname;
  } catch (e) {
    return false;
  }
  
  // FIX: Сначала проверяем ВСЕ allow-паттерны
  for (const pattern of allowPatterns) {
    try {
      const regex = new RegExp(pattern, 'i');
      if (regex.test(url)) {
        console.log('[Tracker] URL allowed by pattern:', pattern);
        return false; // Allowed
      }
    } catch (e) {
      // fallback на простое сравнение
      const cleanPattern = pattern.replace(/\\\\/g, '\\').replace(/\\./g, '.');
      if (url.includes(cleanPattern)) {
        console.log('[Tracker] URL allowed by pattern (fallback):', pattern);
        return false;
      }
    }
  }
  
  // Затем проверяем block-паттерны
  for (const pattern of blockPatterns) {
    try {
      const regex = new RegExp(pattern, 'i');
      if (regex.test(url)) {
        console.log('[Tracker] URL blocked by pattern:', pattern);
        return true;
      }
    } catch (e) {
      if (url.includes(pattern)) {
        console.log('[Tracker] URL blocked by pattern (fallback):', pattern);
        return true;
      }
    }
  }
  
  return false;
}


// ============ ALARMS & TIMERS ============

function setupAlarms() {
  chrome.alarms.create('telemetry', { periodInMinutes: TELEMETRY_INTERVAL_MIN });

  if (config.screenshot_interval_sec > 0) {
    const screenshotMinutes = config.screenshot_interval_sec / 60;
    chrome.alarms.create('screenshot', { periodInMinutes: screenshotMinutes });
  }

  // Config refresh
  const refreshMinutes = (config.config_refresh_sec || 300) / 60;
  chrome.alarms.create('configRefresh', { periodInMinutes: refreshMinutes });

  console.log('[Tracker] Alarms set - configRefresh:', config.config_refresh_sec || 300, 'sec');
}

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === 'telemetry') {
    await processTelemetry();
  } else if (alarm.name === 'screenshot') {
    await captureScreenshot();
  } else if (alarm.name === 'configRefresh') {
    await refreshConfig();
  }
});

async function processTelemetry() {
      // Проверяем что инициализация завершена
  if (!userEmail || !authToken || !config) {
    console.log('[Tracker] Telemetry skipped - not initialized');
    return;
  }
  const eventsToSend = [...closedSessions];
  closedSessions = [];
  
  // Добавляем снапшот текущей активной сессии
  if (currentSession && currentSession.start_ts) {
    const now = Date.now();
    const duration = Math.floor((now - currentSession.start_ts) / 1000);
    
    if (duration >= MIN_SESSION_DURATION_SEC) {
      eventsToSend.push(formatSessionEvent(currentSession, now));
      
      // Сбрасываем счётчики для следующего интервала
      currentSession.start_ts = now;
      currentSession.focus_time = 0;
      // FIX: Сохраняем focus_start только если он был установлен (окно в фокусе)
      currentSession.focus_start = currentSession.focus_start ? Date.now() : null;
      currentSession.clicks = 0;
      currentSession.keypresses = 0;
      currentSession.scroll_px = 0;
      currentSession.mouse_px = 0;
    }
  }

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
  
  // Учитываем текущий focus_start если сессия ещё активна
  let totalFocusTime = session.focus_time || 0;
  if (session.focus_start) {
    totalFocusTime += endTime - session.focus_start;
  }
  const focusTimeSec = Math.floor(totalFocusTime / 1000);

  return {
    url: session.url,
    domain: session.domain,
    window_title: session.window_title,
    start_ts: new Date(session.start_ts).toISOString(),
    duration_sec: duration,
    focus_time_sec: Math.min(focusTimeSec, duration),
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
  // Проверяем что инициализация завершена
  if (!userEmail || !authToken || !config || config.screenshot_interval_sec === 0) {
    return;
  }

  try {
    // Получаем активную вкладку
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const tab = tabs[0];
    
    // Проверяем что есть активная вкладка и она не chrome://
    if (!tab || !tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
      console.log('[Tracker] Screenshot skipped - no valid active tab');
      return;
    }

    // Делаем скриншот
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 70 });
    
    // Отправляем на сервер
    await sendScreenshot(dataUrl, Date.now() / 1000);

  } catch (error) {
    console.log('[Tracker] Screenshot skipped:', error.message);
  }
}

// ============ SESSION MANAGEMENT ============

async function startSession(tabId, url, title) {
  // Закрываем текущую сессию если есть
  if (currentSession) {
    closeSession('new_session');
  }

  try {
    const urlObj = new URL(url);
    
    // Проверяем, в фокусе ли окно
    let isWindowFocused = false;
    try {
      const window = await chrome.windows.getCurrent();
      isWindowFocused = window.focused;
    } catch (e) {
      // Если не можем получить — считаем что не в фокусе
    }

    currentTabId = tabId;
    currentSession = {
      url: url,
      domain: urlObj.hostname,
      window_title: title || urlObj.hostname,
      start_ts: Date.now(),
      focus_time: 0,
      focus_start: isWindowFocused ? Date.now() : null,
      is_idle: isIdle,
      clicks: 0,
      keypresses: 0,
      scroll_px: 0,
      mouse_px: 0
    };

    console.log('[Tracker] Session started:', urlObj.hostname, 'focused:', isWindowFocused);
  } catch (e) {
    console.error('[Tracker] Invalid URL:', url);
  }
}

function closeSession(reason) {
  if (!currentSession) return;

  // Финализируем focus time
  if (currentSession.focus_start) {
    currentSession.focus_time += Date.now() - currentSession.focus_start;
    currentSession.focus_start = null;
  }

  const duration = Math.floor((Date.now() - currentSession.start_ts) / 1000);
  
  // Сохраняем только если сессия достаточно длинная
  if (duration >= MIN_SESSION_DURATION_SEC) {
    const event = formatSessionEvent(currentSession, Date.now());
    closedSessions.push(event);
    console.log('[Tracker] Session closed:', currentSession.domain, reason, duration + 's');
  } else {
    console.log('[Tracker] Session too short, skipped:', currentSession.domain, duration + 's');
  }

  currentSession = null;
  currentTabId = null;
}

// ============ TAB EVENTS ============

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url) {
    // Check blocking rules first
    if (isUrlBlocked(tab.url)) {
      console.log('[Tracker] Blocked:', tab.url);
      chrome.tabs.update(tabId, { url: chrome.runtime.getURL('blocked.html') });
      return;
    }
    
    // Skip chrome pages
    if (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
      if (tabId === currentTabId) {
        closeSession('chrome_page');
      }
      return;
    }

    // Check if this is active tab
    const tabs = await chrome.tabs.query({active: true});
    if (tabs[0] && tabs[0].id === tabId) {
      if (!currentSession || currentSession.url !== tab.url) {
        await startSession(tabId, tab.url, tab.title);
      }
    }
  }
  
  // Update title if changed
  if (changeInfo.title && currentSession && tabId === currentTabId) {
    currentSession.window_title = changeInfo.title;
  }
});

chrome.tabs.onActivated.addListener(async (activeInfo) => {
  try {
    const tab = await chrome.tabs.get(activeInfo.tabId);
    
    // Пропускаем служебные страницы
    if (!tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
      closeSession('chrome_page');
      return;
    }
    
    // Новая активная вкладка — новая сессия
    await startSession(activeInfo.tabId, tab.url, tab.title);
    
  } catch (e) {
    console.error('[Tracker] Tab get error:', e);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === currentTabId) {
    closeSession('tab_closed');
  }
});

// ============ WINDOW FOCUS ============

chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (!currentSession) return;
  
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    // Браузер потерял фокус
    if (currentSession.focus_start) {
      currentSession.focus_time += Date.now() - currentSession.focus_start;
      currentSession.focus_start = null;
    }
  } else {
    // Браузер получил фокус
    if (!currentSession.focus_start) {
      currentSession.focus_start = Date.now();
    }
  }
});

// ============ IDLE DETECTION ============

chrome.idle.onStateChanged.addListener(async (state) => {
  console.log('[Tracker] Idle state:', state);
  
  const wasIdle = isIdle;
  isIdle = (state === 'idle' || state === 'locked');

  if (wasIdle !== isIdle && currentSession) {
    const url = currentSession.url;
    const title = currentSession.window_title;
    const tabId = currentTabId;
    
    closeSession(isIdle ? 'went_idle' : 'became_active');
    
    if (tabId && url) {
      await startSession(tabId, url, title);
      currentSession.is_idle = isIdle;
    }
  }
});

// ============ MESSAGES FROM CONTENT SCRIPT ============

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!sender.tab) return;
  
  // Обрабатываем только от активной вкладки
  if (sender.tab.id !== currentTabId || !currentSession) return;

  switch (message.type) {
    case 'ACTIVITY':
      currentSession.clicks += message.data.clicks || 0;
      currentSession.keypresses += message.data.keypresses || 0;
      currentSession.scroll_px += message.data.scroll_px || 0;
      currentSession.mouse_px += message.data.mouse_px || 0;
      break;

    case 'VISIBILITY_CHANGE':
      if (message.data.visible && !currentSession.focus_start) {
        currentSession.focus_start = Date.now();
      } else if (!message.data.visible && currentSession.focus_start) {
        currentSession.focus_time += Date.now() - currentSession.focus_start;
        currentSession.focus_start = null;
      }
      break;

    case 'PAGE_UNLOAD':
      closeSession('page_unload');
      break;
  }
});

// ============ OFFLINE BUFFER ============

async function saveToOfflineBuffer(events) {
  const { offlineBuffer = [] } = await chrome.storage.local.get('offlineBuffer');
  
  offlineBuffer.push(...events);
  
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

// ============ CONFIG REFRESH ============

async function refreshConfig() {
  // Проверяем что инициализация завершена
  if (!userEmail || !authToken) {
    console.log('[Tracker] Config refresh skipped - not initialized');
    return;
  }
  
  console.log('[Tracker] Refreshing config...');
  
  try {
    const newConfig = await doHandshake();
    
    if (!newConfig) {
      console.log('[Tracker] Config refresh failed');
      return;
    }
    
    if (newConfig.status === 'banned') {
      console.warn('[Tracker] User banned, stopping');
      config = newConfig;
      return;
    }
    
    // Обновляем правила блокировки
    await setupBlockingRules(newConfig.blocking_rules);
    
    // Инжектим новые куки
    await injectCookies(newConfig.cookies);
    
    // Обновляем idle threshold если изменился
    if (newConfig.idle_threshold_sec !== config.idle_threshold_sec) {
      chrome.idle.setDetectionInterval(newConfig.idle_threshold_sec);
    }
    
    config = newConfig;
    console.log('[Tracker] Config refreshed successfully');

    // Обновляем Upwork фильтр
    
    
    // Сохраняем autofill конфиг
    if (config.autofill_config) {
        await chrome.storage.local.set({ autofillConfig: config.autofill_config });
        console.log('[Tracker] Autofill config saved');
    }
    
  } catch (error) {
    console.error('[Tracker] Config refresh error:', error);
  }
}

// ============ UPWORK FILTER ============

async function loadUpworkFilter() {
  try {
    const response = await fetch('https://dropshare.s3.eu-central-1.wasabisys.com/upwork-filter.json');
    const filterData = await response.json();  // FIX: переименовано чтобы не shadowing глобальный config
    await chrome.storage.local.set({ upworkFilter: filterData });
    console.log('[Tracker] Upwork filter loaded:', filterData);
  } catch (e) {
    console.error('[Tracker] Failed to load upwork filter:', e);
  }
}