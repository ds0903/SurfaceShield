(function () {
  'use strict';

  const GREETING = "Hi! I'm the Surface Shield assistant. How can I help you today? 😊\n\nI can answer questions about our roofing, exterior cleaning, auto detailing, or interior cleaning services — or connect you with our team for a free estimate.";

  let history = [];
  let isOpen = false;
  let isTyping = false;
  let leadSaved = false;

  const LEAD_PHRASES = ['will reach out', 'will contact you', 'will get back to you', 'team will reach', 'our team will'];
  const PHONE_RE = /(\+?[\d\s\-().]{7,})/g;

  function tryExtractLead() {
    if (leadSaved) return;
    const lastBotMsg = [...history].reverse().find(m => m.role === 'bot')?.text || '';
    const isLeadConfirmed = LEAD_PHRASES.some(p => lastBotMsg.toLowerCase().includes(p));
    if (!isLeadConfirmed) return;

    // Scan user messages for phone
    let name = '', phone = '', service = '';
    for (const m of history) {
      if (m.role !== 'user') continue;
      const phones = m.text.match(PHONE_RE);
      if (phones) phone = phones[0].trim();
    }
    if (!phone) return;

    // Try to extract name from history (first user message that bot acknowledged with a name)
    for (const m of history) {
      if (m.role === 'bot' && m.text.match(/\b([A-Z][a-z]+)[,!]/)) {
        name = m.text.match(/\b([A-Z][a-z]+)[,!]/)[1];
        break;
      }
    }
    if (!name) {
      // fallback: first word of first user message
      const firstUser = history.find(m => m.role === 'user');
      name = firstUser?.text?.split(/\s/)[0] || 'Unknown';
    }

    // Detect service from conversation
    const allText = history.map(m => m.text).join(' ').toLowerCase();
    if (allText.includes('roof') || allText.includes('restoration') || allText.includes('storm')) service = 'restoration';
    else if (allText.includes('exterior') || allText.includes('wash') || allText.includes('pressure')) service = 'exterior';
    else if (allText.includes('auto') || allText.includes('car') || allText.includes('vehicle') || allText.includes('detailing')) service = 'auto';
    else if (allText.includes('interior') || allText.includes('clean') || allText.includes('home')) service = 'interior';

    const conversation = history.map(m => `${m.role === 'user' ? 'Visitor' : 'Bot'}: ${m.text}`).join('\n');

    leadSaved = true;
    fetch('/api/save-lead/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrf() },
      body: JSON.stringify({ name, phone, service, conversation })
    }).catch(() => {});
  }

  function getCsrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

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
        position: absolute; inset: -4px; border-radius: 50%;
        background: rgba(58,142,230,0.3);
        animation: ss-pulse 2s ease-in-out infinite;
      }
      @keyframes ss-pulse {
        0%,100% { transform: scale(1); opacity: 0.6; }
        50%      { transform: scale(1.3); opacity: 0; }
      }
      #ss-chat-btn.open .ss-pulse { display: none; }
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
        overflow: hidden;
        transform: scale(0.85) translateY(20px);
        opacity: 0; pointer-events: none;
        transform-origin: bottom right;
        transition: transform 0.25s cubic-bezier(.34,1.56,.64,1), opacity 0.2s;
      }
      #ss-chat-win.visible {
        transform: scale(1) translateY(0);
        opacity: 1; pointer-events: all;
      }
      .ss-chat-header {
        background: #050c23;
        padding: 14px 16px; display: flex; align-items: center; gap: 10px;
        border-bottom: 2px solid #1a3a6b;
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
        word-break: break-word; white-space: pre-wrap;
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
        display: flex; gap: 8px; align-items: center;
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
      }
    `;

    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    const faviconSrc = document.querySelector('link[rel="icon"]')?.href || '';

    document.body.insertAdjacentHTML('beforeend', `
      <button id="ss-chat-btn" aria-label="Chat with us">
        <span class="ss-pulse"></span>
        <img src="${faviconSrc}" alt="Surface Shield">
        <span class="ss-close-icon"><i class="fas fa-times"></i></span>
      </button>

      <div id="ss-chat-win" role="dialog" aria-label="Surface Shield Chat">
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
    div.innerHTML = `<div class="ss-msg-bubble">${escHtml(text)}</div>`;
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

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
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

    // Greeting
    addMessage('bot', GREETING);

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
