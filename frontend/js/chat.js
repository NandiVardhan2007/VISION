/**
 * VISION AI — Chat Module
 * Message rendering, markdown support, streaming animation, voice toggle
 */

const VisionChat = (() => {
  let messagesContainer = null;
  let inputField = null;
  let sendBtn = null;
  let micBtn = null;
  let isProcessing = false;
  let typingEl = null;

  function init() {
    messagesContainer = document.getElementById('chat-messages');
    inputField = document.getElementById('chat-input');
    sendBtn = document.getElementById('chat-send');
    micBtn = document.getElementById('chat-mic');

    if (!inputField) return;

    inputField.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    inputField.addEventListener('input', autoResize);

    if (sendBtn) sendBtn.addEventListener('click', sendMessage);
    if (micBtn) micBtn.addEventListener('click', toggleVoiceInput);

    addWelcomeMessage();
  }

  function autoResize() {
    inputField.style.height = 'auto';
    inputField.style.height = Math.min(inputField.scrollHeight, 120) + 'px';
  }

  function addWelcomeMessage() {
    const welcome = `Hey Nandu! 👋 I'm **VISION**, your autonomous AI operating system. I can control your desktop, manage files, browse the web, run code, and so much more.\n\nType anything or hit \`Ctrl+K\` to open the command palette!`;
    appendMessage('assistant', welcome);
  }

  async function sendMessage() {
    const text = inputField.value.trim();
    if (!text || isProcessing) return;

    appendMessage('user', text);
    inputField.value = '';
    inputField.style.height = 'auto';
    setProcessing(true);
    showTyping();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: 'vision_hud_session',
          synthesize_voice: false
        })
      });

      const data = await res.json();
      hideTyping();

      if (data.response) {
        await appendMessageAnimated('assistant', data.response, data.provider, data.latency_ms);
      } else if (data.detail) {
        appendMessage('assistant', `⚠️ Error: ${data.detail}`);
      }

      if (typeof VisionApp !== 'undefined' && VisionApp.showToast) {
        // Optionally log event
      }
    } catch (err) {
      hideTyping();
      appendMessage('assistant', `❌ Connection error: ${err.message}. Is the VISION backend running?`);
    } finally {
      setProcessing(false);
    }
  }

  function setProcessing(state) {
    isProcessing = state;
    if (sendBtn) sendBtn.disabled = state;
  }

  function showTyping() {
    if (typingEl) return;
    typingEl = document.createElement('div');
    typingEl.className = 'chat-message assistant';
    typingEl.innerHTML = `
      <div class="chat-avatar ai">V</div>
      <div class="chat-bubble" style="padding: 10px 16px;">
        <div class="typing-indicator">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    `;
    messagesContainer.appendChild(typingEl);
    scrollToBottom();
  }

  function hideTyping() {
    if (typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  }

  function appendMessage(role, content) {
    const el = createMessageEl(role, content);
    messagesContainer.appendChild(el);
    scrollToBottom();
  }

  async function appendMessageAnimated(role, content, provider, latencyMs) {
    const el = createMessageEl(role, '');
    messagesContainer.appendChild(el);
    const bubbleContent = el.querySelector('.bubble-content');

    // Animate character by character (fast streaming effect)
    const chars = content.split('');
    let rendered = '';
    const chunkSize = 3;

    for (let i = 0; i < chars.length; i += chunkSize) {
      rendered += chars.slice(i, i + chunkSize).join('');
      bubbleContent.innerHTML = formatMarkdown(rendered);
      scrollToBottom();
      const lastChar = chars[Math.min(i + chunkSize - 1, chars.length - 1)];
      const delay = '.!?'.includes(lastChar) ? 30 : ' \n'.includes(lastChar) ? 8 : 5;
      await sleep(delay);
    }

    // Add meta info
    const meta = el.querySelector('.msg-meta');
    if (meta) {
      const time = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
      let info = time;
      if (provider) info += ` · ${provider}`;
      if (latencyMs) info += ` · ${Math.round(latencyMs)}ms`;
      meta.textContent = info;
    }
  }

  function createMessageEl(role, content) {
    const div = document.createElement('div');
    div.className = `chat-message ${role}`;

    const isUser = role === 'user';
    const avatar = isUser
      ? '<div class="chat-avatar human">N</div>'
      : '<div class="chat-avatar ai">V</div>';

    const formattedContent = content ? formatMarkdown(content) : '';

    div.innerHTML = `
      ${avatar}
      <div class="chat-bubble">
        <div class="bubble-content">${formattedContent}</div>
        <span class="msg-meta msg-time"></span>
      </div>
    `;

    if (isUser) {
      const time = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
      div.querySelector('.msg-meta').textContent = time;
    }

    return div;
  }

  function formatMarkdown(text) {
    if (!text) return '';
    let html = text;

    // Code blocks
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre><code class="lang-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  function escapeHtml(str) {
    const el = document.createElement('div');
    el.textContent = str;
    return el.innerHTML;
  }

  function scrollToBottom() {
    if (messagesContainer) {
      requestAnimationFrame(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      });
    }
  }

  async function toggleVoiceInput() {
    if (!micBtn) return;

    if (micBtn.classList.contains('recording')) {
      micBtn.classList.remove('recording');
      if (typeof VisionApp !== 'undefined') VisionApp.showToast('Voice input stopped', 'info');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      micBtn.classList.add('recording');
      if (typeof VisionApp !== 'undefined') VisionApp.showToast('🎙️ Listening... Speak now!', 'info');

      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      const chunks = [];

      mediaRecorder.ondataavailable = (e) => chunks.push(e.data);

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        micBtn.classList.remove('recording');

        const blob = new Blob(chunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('file', blob, 'recording.webm');

        try {
          const res = await fetch('/api/audio/transcribe', { method: 'POST', body: formData });
          const data = await res.json();
          if (data.text && data.text.trim()) {
            inputField.value = data.text;
            if (typeof VisionApp !== 'undefined') VisionApp.showToast('✅ Transcribed!', 'success');
          }
        } catch (err) {
          if (typeof VisionApp !== 'undefined') VisionApp.showToast('Transcription failed', 'error');
        }
      };

      mediaRecorder.start();

      // Auto-stop after 10 seconds
      setTimeout(() => {
        if (mediaRecorder.state === 'recording') mediaRecorder.stop();
      }, 10000);

      // Click to stop early
      micBtn.onclick = () => {
        if (mediaRecorder.state === 'recording') mediaRecorder.stop();
        micBtn.onclick = toggleVoiceInput;
      };

    } catch (err) {
      if (typeof VisionApp !== 'undefined') VisionApp.showToast('Microphone access denied', 'error');
    }
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  return { init, appendMessage, sendMessage };
})();
