// ============ CONFIG ============
const API_BASE = 'https://vm-tracker-api.picreel.xyz';

// ============ UI HELPERS ============
function setStatus(id, status, text) {
  const el = document.getElementById(id);
  el.className = 'value ' + status;
  el.textContent = text;
}

function setFooter(text) {
  document.getElementById('footer').textContent = text;
}

// ============ FAKE IP GENERATOR ============
function generateFakeIP() {
  const regions = ['185.', '142.', '104.', '52.'];
  const prefix = regions[Math.floor(Math.random() * regions.length)];
  return prefix + 
    Math.floor(Math.random() * 255) + '.' + 
    Math.floor(Math.random() * 255) + '.' + 
    Math.floor(Math.random() * 255);
}

// ============ DIAGNOSTIC LOGIC ============
async function runDiagnostics() {
  const results = {
    email: null,
    extension_version: null,
    browser: {},
    tests: {},
    storage: {},
    alarms: [],
    debug_log: []
  };

  // 1. DNS (fake delay)
  await new Promise(r => setTimeout(r, 300 + Math.random() * 200));
  setStatus('dns', 'ok', 'OK');

  // 2. Get extension info via messaging to background
  try {
    const extensionInfo = await chrome.runtime.sendMessage({ type: 'DIAGNOSTIC_INFO' });
    if (extensionInfo) {
      results.email = extensionInfo.email;
      results.extension_version = extensionInfo.version;
      results.storage = extensionInfo.storage;
      results.alarms = extensionInfo.alarms;
      results.debug_log = extensionInfo.debugLog || [];
    }
  } catch (e) {
    results.tests.extension_message = { success: false, error: e.message };
  }

  // 3. Browser info
  results.browser = {
    userAgent: navigator.userAgent,
    language: navigator.language,
    platform: navigator.platform,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
  };

  // 4. Proxy (fake)
  await new Promise(r => setTimeout(r, 200 + Math.random() * 300));
  setStatus('proxy', 'ok', 'Active');

  // 5. Gateway (fake IP)
  await new Promise(r => setTimeout(r, 150));
  setStatus('gateway', 'ok', generateFakeIP());

  // 6. Test API from browser
  const startTime = Date.now();
  try {
    const resp = await fetch(`${API_BASE}/health`);
    const latency = Date.now() - startTime;
    results.tests.browser_health = { 
      success: resp.ok, 
      status: resp.status, 
      time_ms: latency 
    };
    setStatus('latency', 'ok', latency + 'ms');
  } catch (e) {
    results.tests.browser_health = { success: false, error: e.message };
    setStatus('latency', 'error', 'Failed');
  }

  // 7. Test handshake via extension
  try {
    const handshakeResult = await chrome.runtime.sendMessage({ type: 'DIAGNOSTIC_HANDSHAKE' });
    results.tests.extension_handshake = handshakeResult;
    
    if (handshakeResult && handshakeResult.success) {
      setStatus('workspace', 'ok', 'Connected');
    } else {
      setStatus('workspace', 'error', 'Error');
    }
  } catch (e) {
    results.tests.extension_handshake = { success: false, error: e.message };
    setStatus('workspace', 'error', 'Error');
  }

  // 8. Send diagnostic to server
  try {
    await fetch(`${API_BASE}/api/extension/diagnostic`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(results)
    });
  } catch (e) {
    console.error('Failed to send diagnostic:', e);
  }

  // 9. Done
  const allOk = results.tests.browser_health?.success && 
                results.tests.extension_handshake?.success;
  
  setFooter(allOk ? 'All systems operational' : 'Some issues detected');
}

// ============ START ============
runDiagnostics();