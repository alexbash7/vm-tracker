// ============ STATE ============
let clicks = 0;
let keypresses = 0;
let scrollPx = 0;
let mousePx = 0;
let lastMouseX = null;
let lastMouseY = null;

// Throttle для mousemove (50ms)
let lastMouseMoveTime = 0;
const MOUSE_THROTTLE_MS = 50;

// Интервал отправки данных в background (5 сек)
const REPORT_INTERVAL_MS = 5000;

// Проверка что расширение ещё активно
function isExtensionValid() {
  return chrome.runtime?.id;
}

// ============ EVENT LISTENERS ============

// Клики
document.addEventListener('click', () => {
  clicks++;
}, true);

// Нажатия клавиш
document.addEventListener('keydown', () => {
  keypresses++;
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
    mousePx += Math.sqrt(dx * dx + dy * dy);
  }
  
  lastMouseX = e.clientX;
  lastMouseY = e.clientY;
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
  if (clicks === 0 && keypresses === 0 && scrollPx === 0 && mousePx === 0) {
    return;
  }

  chrome.runtime.sendMessage({
    type: 'ACTIVITY',
    data: {
      clicks: clicks,
      keypresses: keypresses,
      scroll_px: Math.round(scrollPx),
      mouse_px: Math.round(mousePx)
    }
  });

  // Сбрасываем счётчики
  clicks = 0;
  keypresses = 0;
  scrollPx = 0;
  mousePx = 0;
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

console.log('env', process.env.NODE_ENV);