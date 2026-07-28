(function () {
  'use strict';

  const GREETING = "Hi! I'm the Surface Shield assistant. How can I help you today? 😊\n\nI can answer questions about our roofing, exterior cleaning, auto detailing, or interior cleaning services — or connect you with our team for a free estimate.";

  let history = [];
  let isOpen = false;
  let isTyping = false;
  let leadSaved = false;

  const LS_KEY = 'ss_chat_v1';
  const LS_TTL = 12 * 60 * 60 * 1000; // 12 hours

  function storageSave() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ ts: Date.now(), history }));
    } catch(e) {}
  }

  function storageLoad() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return false;
      const obj = JSON.parse(raw);
      if (Date.now() - obj.ts > LS_TTL) { localStorage.removeItem(LS_KEY); return false; }
      history = obj.history || [];
      return history.length > 0;
    } catch(e) { return false; }
  }

  const LEAD_PHRASES = ['will reach out', 'will contact you', 'will get back to you', 'team will reach', 'our team will', 'noted your information'];
  const PHONE_RE = /(\+?1?[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})/g;
  const EMAIL_RE = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;

  function _getUtm() {
    const p = new URLSearchParams(window.location.search);
    return {
      utm_source: p.get('utm_source') || sessionStorage.getItem('utm_source') || '',
      utm_medium: p.get('utm_medium') || sessionStorage.getItem('utm_medium') || '',
      utm_campaign: p.get('utm_campaign') || sessionStorage.getItem('utm_campaign') || '',
    };
  }

  (function() {
    const p = new URLSearchParams(window.location.search);
    if (p.get('utm_source')) sessionStorage.setItem('utm_source', p.get('utm_source'));
    if (p.get('utm_medium')) sessionStorage.setItem('utm_medium', p.get('utm_medium'));
    if (p.get('utm_campaign')) sessionStorage.setItem('utm_campaign', p.get('utm_campaign'));
  })();

  function tryExtractLead() {
    if (leadSaved) return;
    const lastBotMsg = [...history].reverse().find(m => m.role === 'bot')?.text || '';
    const isLeadConfirmed = LEAD_PHRASES.some(p => lastBotMsg.toLowerCase().includes(p));
    if (!isLeadConfirmed) return;

    const allUserText = history.filter(m => m.role === 'user').map(m => m.text).join(' ');
    const allText = history.map(m => m.text).join(' ').toLowerCase();

    let phone = '';
    for (const m of history) {
      if (m.role !== 'user') continue;
      const phones = m.text.match(PHONE_RE);
      if (phones) { phone = phones[0].trim(); break; }
    }
    if (!phone) return;

    let email = '';
    const emails = allUserText.match(EMAIL_RE);
    if (emails) email = emails[0];

    let name = '';
    for (const m of history) {
      if (m.role === 'bot' && m.text.match(/\b([A-Z][a-z]+)[,!]/)) {
        name = m.text.match(/\b([A-Z][a-z]+)[,!]/)[1];
        break;
      }
    }
    if (!name) {
      const firstUser = history.find(m => m.role === 'user');
      name = firstUser?.text?.split(/\s/)[0] || 'Unknown';
    }

    let service = '';
    if (allText.includes('roof') || allText.includes('restor') || allText.includes('storm') || allText.includes('shingle')) service = 'restoration';
    else if (allText.includes('exterior') || allText.includes('wash') || allText.includes('pressure') || allText.includes('soft wash')) service = 'exterior';
    else if (allText.includes('auto') || allText.includes('car') || allText.includes('vehicle') || allText.includes('detail') || allText.includes('ceramic')) service = 'auto';
    else if (allText.includes('interior') || allText.includes('clean') || allText.includes('deep clean')) service = 'interior';

    let preferred_contact = '', call_time = '', address = '', description = '';
    for (let i = 0; i < history.length; i++) {
      const m = history[i];
      if (m.role !== 'user') continue;
      const prev = history[i - 1]?.text?.toLowerCase() || '';
      if (prev.includes('contact') && (prev.includes('call') || prev.includes('text'))) preferred_contact = m.text.slice(0, 50);
      if (prev.includes('time') || prev.includes('when')) call_time = m.text.slice(0, 80);
      if (prev.includes('address') || prev.includes('property') || prev.includes('location')) address = m.text.slice(0, 200);
      if (prev.includes('describe') || prev.includes('tell us') || prev.includes('project')) description = m.text.slice(0, 300);
    }

    const conversation = history.map(m => `${m.role === 'user' ? 'Visitor' : 'Bot'}: ${m.text}`).join('\n');
    const utm = _getUtm();

    leadSaved = true;
    fetch('/api/save-lead/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
      body: JSON.stringify({
        name, phone, email, address, service, description,
        preferred_contact, call_time,
        page_url: window.location.href,
        referrer: document.referrer,
        ...utm,
        conversation
      })
    }).catch(() => {});
  }

  function getCsrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  // ── Markdown renderer (bot messages only) ──────────────────────────────────
  function applyInline(s) {
    return s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  }

  function renderMarkdown(raw) {
    const esc = raw
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    const lines = esc.split('\n');
    const out = [];
    let inList = false;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const bullet = line.match(/^\s*[*\-]\s+(.*)/);
      if (bullet) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push('<li>' + applyInline(bullet[1]) + '</li>');
      } else {
        if (inList) { out.push('</ul>'); inList = false; }
        if (line === '') {
          out.push('<br>');
        } else {
          out.push(applyInline(line) + (i < lines.length - 1 ? '<br>' : ''));
        }
      }
    }
    if (inList) out.push('</ul>');
    return out.join('');
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
  }
  // ──────────────────────────────────────────────────────────────────────────

  function buildWidget() {
    const css = `
      #ss-chat-btn {
        position: fixed; bottom: 24px; right: 24px; z-index: 9999;
        width: 60px; height: 60px; border-radius: 50%;
        background: #050c23;
        border: 2px solid #3a8ee6;
        box-shadow: 0 4px 24px rgba(58,142,230,0.35);
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: transform 0.2s, box-shadow 0.2s;
      }
      #ss-chat-btn:hover { transform: scale(1.08); box-shadow: 0 6px 28px rgba(58,142,230,0.55); }
      #ss-chat-btn img { width: 36px; height: 36px; object-fit: contain; }
      #ss-chat-btn .ss-pulse {
        position: absolute; inset: -8px; border-radius: 50%;
        background: transparent;
        border: 2px solid rgba(58,142,230,0.7);
        animation: ss-pulse 1.6s ease-out infinite;
        pointer-events: none;
      }
      #ss-chat-btn .ss-pulse2 {
        position: absolute; inset: -16px; border-radius: 50%;
        background: transparent;
        border: 2px solid rgba(58,142,230,0.35);
        animation: ss-pulse 1.6s ease-out 0.5s infinite;
        pointer-events: none;
      }
      @keyframes ss-pulse {
        0%   { transform: scale(0.9); opacity: 1; }
        100% { transform: scale(1.5); opacity: 0; }
      }
      #ss-chat-btn.open .ss-pulse,
      #ss-chat-btn.open .ss-pulse2 { display: none; }
      #ss-chat-btn .ss-close-icon { display: none; color: #fff; font-size: 22px; }
      #ss-chat-btn.open img { display: none; }
      #ss-chat-btn.open .ss-close-icon { display: block; }

      #ss-chat-win {
        position: fixed; bottom: 96px; right: 24px; z-index: 9998;
        width: 340px; max-width: calc(100vw - 32px);
        height: 480px; max-height: calc(100vh - 120px);
        background: #fff; border-radius: 16px;
        box-shadow: 0 8px 40px rgba(5,12,35,0.22);
        display: flex; flex-direction: column;
        overflow: visible;
        transform: scale(0.85) translateY(20px);
        opacity: 0; pointer-events: none;
        transform-origin: bottom right;
        transition: transform 0.25s cubic-bezier(.34,1.56,.64,1), opacity 0.2s;
      }
      #ss-chat-win.visible {
        transform: scale(1) translateY(0);
        opacity: 1; pointer-events: all;
      }

      /* ── Resize handle ── */
      .ss-chat-resize {
        position: absolute; top: -10px; left: -10px;
        width: 28px; height: 28px;
        cursor: nw-resize;
        z-index: 10000;
        background: #1a3a6b;
        border-radius: 50%;
        border: 2px solid #3a8ee6;
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        transition: background 0.15s;
      }
      .ss-chat-resize:hover { background: #3a8ee6; }
      .ss-chat-resize::before {
        content: '⤡';
        color: #fff;
        font-size: 13px;
        line-height: 1;
        transform: rotate(-45deg);
        display: block;
      }

      .ss-chat-header {
        background: #050c23;
        padding: 14px 16px; display: flex; align-items: center; gap: 10px;
        border-bottom: 2px solid #1a3a6b;
        flex-shrink: 0;
        border-radius: 16px 16px 0 0;
        overflow: hidden;
      }
      .ss-chat-header img { width: 34px; height: 34px; object-fit: contain; border-radius: 50%; }
      .ss-chat-header-text { flex: 1; }
      .ss-chat-header-name { font-family: 'Montserrat', sans-serif; font-weight: 800; font-size: 13px; color: #fff; }
      .ss-chat-header-status { font-size: 11px; color: rgba(255,255,255,0.55); }
      .ss-chat-online { display: inline-block; width: 7px; height: 7px; background: #4caf50; border-radius: 50%; margin-right: 4px; }

      .ss-chat-msgs {
        flex: 1; overflow-y: auto; padding: 14px 12px; display: flex; flex-direction: column; gap: 10px;
        background: #f7f9fc;
      }
      .ss-chat-msgs::-webkit-scrollbar { width: 4px; }
      .ss-chat-msgs::-webkit-scrollbar-thumb { background: #d0d8e8; border-radius: 4px; }

      .ss-msg { max-width: 82%; }
      .ss-msg.bot { align-self: flex-start; }
      .ss-msg.user { align-self: flex-end; }
      .ss-msg-bubble {
        padding: 9px 13px; border-radius: 14px; font-size: 13px; line-height: 1.5;
        word-break: break-word;
      }
      .ss-msg.bot .ss-msg-bubble {
        background: #fff; color: #1a1a2e;
        border: 1px solid #e4eaf2;
        border-bottom-left-radius: 4px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
      }
      .ss-msg.user .ss-msg-bubble {
        background: #1a3a6b;
        color: #fff; border-bottom-right-radius: 4px;
      }
      .ss-msg-bubble ul { margin: 4px 0 4px 16px; padding: 0; }
      .ss-msg-bubble li { margin-bottom: 3px; }

      .ss-typing { display: flex; align-items: center; gap: 4px; padding: 10px 13px; }
      .ss-typing span {
        width: 7px; height: 7px; border-radius: 50%; background: #9bacc8;
        animation: ss-dot 1.2s infinite;
      }
      .ss-typing span:nth-child(2) { animation-delay: 0.2s; }
      .ss-typing span:nth-child(3) { animation-delay: 0.4s; }
      @keyframes ss-dot { 0%,80%,100%{transform:scale(1);opacity:0.4} 40%{transform:scale(1.3);opacity:1} }

      .ss-chat-footer {
        padding: 10px 12px; background: #fff; border-top: 1px solid #eef1f7;
        display: flex; gap: 8px; align-items: center; flex-shrink: 0;
        border-radius: 0 0 16px 16px;
        overflow: hidden;
      }
      #ss-chat-input {
        flex: 1; border: 1px solid #d8e0ee; border-radius: 20px;
        padding: 8px 14px; font-size: 13px; outline: none; resize: none;
        max-height: 80px; overflow-y: auto; line-height: 1.4;
        font-family: 'Open Sans', sans-serif;
      }
      #ss-chat-input:focus { border-color: #3a8ee6; }
      #ss-chat-send {
        width: 36px; height: 36px; border-radius: 50%; border: none; cursor: pointer;
        background: #3a8ee6;
        color: #fff; display: flex; align-items: center; justify-content: center;
        font-size: 14px; flex-shrink: 0; transition: opacity 0.2s, background 0.2s;
      }
      #ss-chat-send:hover:not(:disabled) { background: #1a3a6b; }
      #ss-chat-send:disabled { opacity: 0.4; cursor: default; }

      @media (max-width: 480px) {
        #ss-chat-win { width: calc(100vw - 24px); right: 12px; bottom: 88px; }
        #ss-chat-btn { right: 12px; bottom: 16px; }
        .ss-chat-resize { display: none; }
      }
    `;

    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    const faviconSrc = document.querySelector('link[rel="icon"]')?.href || '';

    document.body.insertAdjacentHTML('beforeend', `
      <button id="ss-chat-btn" aria-label="Chat with us">
        <span class="ss-pulse"></span>
        <span class="ss-pulse2"></span>
        <img src="${faviconSrc}" alt="Surface Shield">
        <span class="ss-close-icon"><i class="fas fa-times"></i></span>
      </button>

      <div id="ss-chat-win" role="dialog" aria-label="Surface Shield Chat">
        <div class="ss-chat-resize" title="Resize"></div>
        <div class="ss-chat-header">
          <img src="${faviconSrc}" alt="">
          <div class="ss-chat-header-text">
            <div class="ss-chat-header-name">Surface Shield Assistant</div>
            <div class="ss-chat-header-status"><span class="ss-chat-online"></span>Online</div>
          </div>
        </div>
        <div class="ss-chat-msgs" id="ss-chat-msgs"></div>
        <div class="ss-chat-footer">
          <textarea id="ss-chat-input" placeholder="Ask about our services…" rows="1"></textarea>
          <button id="ss-chat-send"><i class="fas fa-paper-plane"></i></button>
        </div>
      </div>
    `);
  }

  function addMessage(role, text) {
    const msgs = document.getElementById('ss-chat-msgs');
    const div = document.createElement('div');
    div.className = `ss-msg ${role}`;
    const content = role === 'bot' ? renderMarkdown(text) : escHtml(text);
    div.innerHTML = `<div class="ss-msg-bubble">${content}</div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function showTyping() {
    const msgs = document.getElementById('ss-chat-msgs');
    const div = document.createElement('div');
    div.className = 'ss-msg bot';
    div.id = 'ss-typing-indicator';
    div.innerHTML = `<div class="ss-msg-bubble ss-typing"><span></span><span></span><span></span></div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function hideTyping() {
    document.getElementById('ss-typing-indicator')?.remove();
  }

  function initResize(win) {
    const handle = win.querySelector('.ss-chat-resize');
    let startX, startY, startW, startH;

    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      startX = e.clientX;
      startY = e.clientY;
      startW = win.offsetWidth;
      startH = win.offsetHeight;

      function onMove(e) {
        const dx = startX - e.clientX;
        const dy = startY - e.clientY;
        const newW = Math.max(280, Math.min(640, startW + dx));
        const newH = Math.max(360, Math.min(window.innerHeight - 140, startH + dy));
        win.style.width = newW + 'px';
        win.style.height = newH + 'px';
      }

      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  async function sendMessage(text) {
    if (isTyping || !text.trim()) return;
    isTyping = true;

    addMessage('user', text);
    document.getElementById('ss-chat-input').value = '';
    document.getElementById('ss-chat-send').disabled = true;
    autoResize();
    showTyping();

    try {
      const res = await fetch('/api/chat/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
        body: JSON.stringify({ message: text, history })
      });
      const data = await res.json();
      hideTyping();
      const reply = data.reply || data.error || 'Sorry, something went wrong.';
      addMessage('bot', reply);
      history.push({ role: 'user', text }, { role: 'bot', text: reply });
      storageSave();
      tryExtractLead();
    } catch {
      hideTyping();
      addMessage('bot', 'Connection issue. Please try again or call us at +1 (216) 280-1855.');
    }

    isTyping = false;
    document.getElementById('ss-chat-send').disabled = false;
  }

  function autoResize() {
    const el = document.getElementById('ss-chat-input');
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 80) + 'px';
  }

  function toggleChat() {
    isOpen = !isOpen;
    const btn = document.getElementById('ss-chat-btn');
    const win = document.getElementById('ss-chat-win');
    btn.classList.toggle('open', isOpen);
    win.classList.toggle('visible', isOpen);
    if (isOpen) {
      setTimeout(() => document.getElementById('ss-chat-input')?.focus(), 250);
    }
  }

  function init() {
    buildWidget();

    const win = document.getElementById('ss-chat-win');
    initResize(win);

    // Restore or show greeting
    if (storageLoad() && history.length > 0) {
      history.forEach(m => addMessage(m.role === 'user' ? 'user' : 'bot', m.text));
    } else {
      addMessage('bot', GREETING);
    }

    document.getElementById('ss-chat-btn').addEventListener('click', toggleChat);

    document.getElementById('ss-chat-send').addEventListener('click', () => {
      sendMessage(document.getElementById('ss-chat-input').value.trim());
    });

    document.getElementById('ss-chat-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage(e.target.value.trim());
      }
    });

    document.getElementById('ss-chat-input').addEventListener('input', autoResize);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
