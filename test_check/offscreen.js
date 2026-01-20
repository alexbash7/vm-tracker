// Offscreen document для захвата скриншотов
// В Manifest V3 service worker не имеет доступа к DOM,
// поэтому некоторые операции требуют offscreen document

// Слушаем сообщения от background.js
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CAPTURE_SCREENSHOT') {
    // Здесь можно добавить дополнительную обработку скриншота
    // например, сжатие или конвертацию
    sendResponse({ success: true });
  }
});

console.log('[Tracker] Offscreen document ready');