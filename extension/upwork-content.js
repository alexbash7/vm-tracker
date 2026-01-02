// ============ UPWORK CONTENT FILTER ============

(function() {
  'use strict';

  // Скрываем страницу до загрузки фильтра
  const style = document.createElement('style');
  style.textContent = 'body { visibility: hidden !important; }';
  document.documentElement.appendChild(style);

  let HIDDEN = { ids: [], titles: [] };
  let initialized = false;
  let domReady = false;

  // Загружаем конфиг из storage
  chrome.storage.local.get('upworkFilter', (result) => {
    if (result.upworkFilter) {
      HIDDEN = result.upworkFilter;
      console.log('[Upwork Filter] Config loaded:', HIDDEN);
    }
    initialized = true;
    tryInit();
  });

  function hideItems() {
    if (!initialized || !document.body) return;

    HIDDEN.ids.forEach(id => {
      document.querySelectorAll(`a[href*="${id}"], [data-test*="${id}"]`).forEach(hideParent);
    });

    HIDDEN.titles.forEach(title => {
      document.querySelectorAll('h2[title], h4, [data-test="room-topic-or-subtitle"], .openings-title-link, .qa-wm-opening-title-link-desktop').forEach(el => {
        const text = el.getAttribute('title') || el.textContent || '';
        if (text.includes(title)) {
          hideParent(el);
        }
      });
    });
  }

  function hideParent(el) {
    const container = el.closest(
      'section.air3-card-section, a.room-list-item, .qa-wm-opening-item, section'
    );
    if (container && container.style.display !== 'none') {
      container.style.display = 'none';
      console.log('[Upwork Filter] Hidden:', el.textContent?.substring(0, 40));
    }
  }

  function handleMessages() {
    if (!window.location.href.includes('/messages/')) return;

    const activeRoom = document.querySelector('a.room-list-item.nuxt-link-active, a.room-list-item[aria-current="page"]');
    if (!activeRoom) return;

    const roomTitle = activeRoom.querySelector('[data-test="room-topic-or-subtitle"]')?.textContent || '';
    const roomHref = activeRoom.getAttribute('href') || '';

    const shouldHide = 
      HIDDEN.titles.some(t => roomTitle.includes(t)) ||
      HIDDEN.ids.some(id => roomHref.includes(id));

    if (shouldHide) {
      const allRooms = document.querySelectorAll('a.room-list-item');
      for (const room of allRooms) {
        if (room === activeRoom) continue;
        if (room.style.display === 'none') continue;
        
        const newHref = room.getAttribute('href');
        if (newHref) {
          window.location.href = newHref;
          return;
        }
      }
    }
  }

  function tryInit() {
    // Ждём и конфиг, и DOM
    if (!initialized || !domReady) return;
    
    if (!document.body) {
      // body ещё нет, ждём
      setTimeout(tryInit, 10);
      return;
    }

    hideItems();
    handleMessages();
    
    // Показываем страницу
    document.body.style.visibility = 'visible';
    style.remove();

    // Следим за изменениями DOM
    new MutationObserver(() => {
      hideItems();
      handleMessages();
    }).observe(document.body, {
      childList: true,
      subtree: true
    });

    console.log('[Upwork Filter] Active');
  }

  // Ждём DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      domReady = true;
      tryInit();
    });
  } else {
    domReady = true;
    tryInit();
  }

  // Таймаут на случай если что-то зависнет
  setTimeout(() => {
    if (!initialized) {
      initialized = true;
      HIDDEN = { ids: [], titles: [] };
    }
    domReady = true;
    tryInit();
  }, 3000);

})();