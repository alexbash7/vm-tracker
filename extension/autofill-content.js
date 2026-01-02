// ============ AUTOFILL CONTENT SCRIPT ============

(function() {
    'use strict';

    let config = null;
    let filledFields = new Set();
    let hiddenElements = new Set();
    let lastUrl = window.location.href;

    // Загружаем конфиг из storage
    chrome.storage.local.get('autofillConfig', (result) => {
        if (result.autofillConfig) {
            config = result.autofillConfig;
            console.log('[Autofill] Config loaded:', config);
            processPage();
            startObserver();
        } else {
            console.log('[Autofill] No config found');
        }
    });

    function matchesUrl(urlPatterns) {
        const currentUrl = window.location.href;
        for (const pattern of urlPatterns) {
            try {
                const regex = new RegExp(pattern, 'i');
                if (regex.test(currentUrl)) {
                    return true;
                }
            } catch (e) {
                console.error('[Autofill] Invalid regex:', pattern);
            }
        }
        return false;
    }

function findElement(selectors) {
    for (const selector of selectors) {
        const el = document.querySelector(selector);
        if (el && el.offsetParent !== null && el.offsetHeight > 0) {
            return el;
        }
    }
    return null;
}

    function processPage() {
        if (!config || !config.rules) return;

        // Сброс при смене URL
        const currentUrl = window.location.href;
        if (currentUrl !== lastUrl) {
            filledFields.clear();
            hiddenElements.clear();
            lastUrl = currentUrl;
            console.log('[Autofill] URL changed, reset state');
        }

        for (const rule of config.rules) {
            if (!matchesUrl(rule.url_match)) continue;

            if (rule.fields) {
                for (const field of rule.fields) {
                    const input = findElement(field.selectors);
                    if (!input) continue;

                    const fieldKey = field.selectors.join('|');
                    if (filledFields.has(fieldKey)) continue;

                    // Помечаем сразу, до таймаута
                    filledFields.add(fieldKey);

                    const delay = field.delay || 500;

                    setTimeout(() => {
                        input.value = field.value;
                        input.dispatchEvent(new Event('input', { bubbles: true }));

                        if (field.hide_value) {
                            input.type = 'password';
                        }

                        console.log('[Autofill] Filled:', field.selectors[0]);
                    }, delay);
                }
            }

            if (rule.hide_elements) {
                for (const selector of rule.hide_elements) {
                    const el = document.querySelector(selector);
                    if (el && !hiddenElements.has(selector)) {
                        el.style.display = 'none';
                        hiddenElements.add(selector);
                        console.log('[Autofill] Hidden:', selector);
                    }
                }
            }
        }
    }

    function startObserver() {
        if (document.body) {
            new MutationObserver(processPage).observe(document.body, {
                childList: true,
                subtree: true
            });
        } else {
            document.addEventListener('DOMContentLoaded', () => {
                new MutationObserver(processPage).observe(document.body, {
                    childList: true,
                    subtree: true
                });
            });
        }
    }

    console.log('[Autofill] Script loaded');
})();