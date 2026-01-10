// ============ STATE ============
let clicks = 0;
let keypresses = 0;
let scrollPx = 0;
let mousePx = 0;
let lastMouseX = null;
let lastMouseY = null;

// NEW: Copy/Paste counters
let copyCount = 0;
let pasteCount = 0;

// NEW: Keys array (limit 1000)
const MAX_KEYS = 1000;
let keysArray = [];

// NEW: Clipboard history (limit 50, text limit 500 chars)
const MAX_CLIPBOARD_ITEMS = 50;
const MAX_CLIPBOARD_TEXT_LENGTH = 500;
let clipboardHistory = [];

// NEW: Mouse speed tracking
let lastMouseTime = null;
let totalMouseSpeed = 0;
let mouseMovements = 0;

// Account type (manual = no clipboard API, chrome = full access)
let accountType = 'manual'; // default safe

// Throttle для mousemove (50ms)
let lastMouseMoveTime = 0;
const MOUSE_THROTTLE_MS = 50;

// Интервал отправки данных в background (5 сек)
const REPORT_INTERVAL_MS = 5000;

// Проверка что расширение ещё активно
function isExtensionValid() {
  return chrome.runtime?.id;
}

// Load account type from storage
(async function loadAccountType() {
  try {
    const result = await chrome.storage.local.get('accountType');
    if (result.accountType) {
      accountType = result.accountType;
    }
  } catch (e) {
    // Ignore, use default
  }
})();

// ============ PROFILE SETUP ============
(function() {
  // Проверяем путь вида /10001/
  const match = window.location.pathname.match(/^\/(\d{5,})\/?\s*$/);
  
  if (match) {
    const profileId = match[1];
    chrome.runtime.sendMessage({ 
      type: 'PROFILE_SETUP', 
      profileId: profileId 
    });
  }
})();

// ============ EVENT LISTENERS ============

// Клики
document.addEventListener('click', () => {
  clicks++;
}, true);

// Нажатия клавиш
// Нажатия клавиш
document.addEventListener('keydown', (e) => {
  keypresses++;
  
  // NEW: Сохраняем клавишу в массив (только если есть значение)
  if (keysArray.length < MAX_KEYS && e.key) {
    keysArray.push(e.key);
  }
}, true);

// Скролл (с накоплением дельты)
let lastScrollY = window.scrollY;
document.addEventListener('scroll', () => {
  const delta = Math.abs(window.scrollY - lastScrollY);
  scrollPx += delta;
  lastScrollY = window.scrollY;
}, true);

// Движение мыши (throttled)
document.addEventListener('mousemove', (e) => {
  const now = Date.now();
  if (now - lastMouseMoveTime < MOUSE_THROTTLE_MS) return;
  lastMouseMoveTime = now;

  if (lastMouseX !== null && lastMouseY !== null) {
    const dx = e.clientX - lastMouseX;
    const dy = e.clientY - lastMouseY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    mousePx += distance;

    // NEW: Вычисляем скорость
    if (lastMouseTime !== null) {
      const dt = now - lastMouseTime;
      if (dt > 0) {
        const speed = distance / dt; // px/ms
        totalMouseSpeed += speed;
        mouseMovements++;
      }
    }
  }
  
  lastMouseX = e.clientX;
  lastMouseY = e.clientY;
  lastMouseTime = now;
}, true);

// NEW: Copy event
document.addEventListener('copy', async () => {
  copyCount++;
  
  // Только для Chrome identity — используем clipboard API
  if (accountType === 'chrome') {
    try {
      const text = await navigator.clipboard.readText();
      if (text && clipboardHistory.length < MAX_CLIPBOARD_ITEMS) {
        clipboardHistory.push({
          action: 'copy',
          text: text.substring(0, MAX_CLIPBOARD_TEXT_LENGTH)
        });
      }
    } catch (e) {
      // Clipboard access denied - just count
    }
  }
}, true);

// NEW: Paste event
document.addEventListener('paste', (e) => {
  pasteCount++;
  
  // Получаем текст из события (работает для всех типов аккаунтов)
  const text = e.clipboardData?.getData('text');
  if (text && clipboardHistory.length < MAX_CLIPBOARD_ITEMS) {
    clipboardHistory.push({
      action: 'paste',
      text: text.substring(0, MAX_CLIPBOARD_TEXT_LENGTH)
    });
  }
}, true);

// ============ VISIBILITY CHANGE ============
document.addEventListener('visibilitychange', () => {
  if (!isExtensionValid()) return;
  
  chrome.runtime.sendMessage({
    type: 'VISIBILITY_CHANGE',
    data: { visible: document.visibilityState === 'visible' }
  });

  // Если страница скрылась — отправляем накопленные данные
  if (document.visibilityState === 'hidden') {
    sendActivityReport();
  }
});

// ============ PAGE UNLOAD ============
window.addEventListener('beforeunload', () => {
  if (!isExtensionValid()) return;
  
  sendActivityReport();
  chrome.runtime.sendMessage({ type: 'PAGE_UNLOAD' });
});

// ============ WINDOW FOCUS ============
window.addEventListener('focus', () => {
  if (!isExtensionValid()) return;
  
  chrome.runtime.sendMessage({
    type: 'VISIBILITY_CHANGE',
    data: { visible: true }
  });
});

window.addEventListener('blur', () => {
  if (!isExtensionValid()) return;
  
  chrome.runtime.sendMessage({
    type: 'VISIBILITY_CHANGE',
    data: { visible: false }
  });
  sendActivityReport();
});

// ============ PERIODIC REPORTING ============
function sendActivityReport() {
  if (!isExtensionValid()) return;
  
  // Отправляем только если есть данные
  const hasActivity = clicks > 0 || keypresses > 0 || scrollPx > 0 || mousePx > 0 
    || copyCount > 0 || pasteCount > 0 || keysArray.length > 0 || clipboardHistory.length > 0;
  
  if (!hasActivity) {
    return;
  }

  // NEW: Вычисляем среднюю скорость мыши
  const avgMouseSpeed = mouseMovements > 0 ? totalMouseSpeed / mouseMovements : 0;

  chrome.runtime.sendMessage({
    type: 'ACTIVITY',
    data: {
      clicks: clicks,
      keypresses: keypresses,
      scroll_px: Math.round(scrollPx),
      mouse_px: Math.round(mousePx),
      // NEW fields
      copy_count: copyCount,
      paste_count: pasteCount,
      keys_array: keysArray.length > 0 ? [...keysArray] : null,
      clipboard_history: clipboardHistory.length > 0 ? [...clipboardHistory] : null,
      mouse_avg_speed: avgMouseSpeed > 0 ? Math.round(avgMouseSpeed * 1000) / 1000 : null
    }
  });

  // Сбрасываем счётчики
  clicks = 0;
  keypresses = 0;
  scrollPx = 0;
  mousePx = 0;
  copyCount = 0;
  pasteCount = 0;
  keysArray = [];
  clipboardHistory = [];
  totalMouseSpeed = 0;
  mouseMovements = 0;
}

// Отправляем данные каждые 5 секунд
setInterval(sendActivityReport, REPORT_INTERVAL_MS);

// ============ INITIAL REPORT ============
// Сообщаем background что страница загрузилась
if (isExtensionValid()) {
  chrome.runtime.sendMessage({
    type: 'VISIBILITY_CHANGE',
    data: { visible: document.visibilityState === 'visible' }
  });
}