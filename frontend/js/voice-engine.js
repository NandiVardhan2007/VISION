/**
 * VISION AI — Voice Engine
 * VAD (Voice Activity Detection), microphone management, recording pipeline
 */

const VisionVoice = (() => {
  let handsFreeEnabled = true;
  let isMuted = false;
  let isProcessing = false;
  let micStream = null;
  let audioContext = null;
  let analyser = null;
  let mediaRecorder = null;
  let recordedChunks = [];
  let isUserSpeaking = false;
  let speechStartTime = 0;
  let lastSpeechTime = 0;
  let vadCheckInterval = null;
  let isManualRecording = false;
  let speechTimeout = null;

  // VAD Tuning - Robust Noise & Hallucination Suppression
  let ambientNoiseFloor = 0.015;
  let consecutiveSpeechFrames = 0;
  const REQUIRED_SPEECH_FRAMES = 4; // 160ms continuous voice energy required
  const MIN_SPEECH_DURATION_MS = 700; // Minimum 700ms spoken audio

  const API_BASE = (window.location.origin.startsWith('http')) ? '' : 'http://localhost:8000';

  // DOM elements (cached on init)
  let muteBtn, muteIconContainer, muteLabel, micBtn, mainMicIcon;
  let handsfreeBtn, handsfreeLabel, orbHitbox;
  let cmdInput, sendBtn, statusText, statusDot;

  function init() {
    muteBtn          = document.getElementById('mute-btn');
    muteIconContainer = document.getElementById('mute-icon-container');
    muteLabel        = document.getElementById('mute-label');
    micBtn           = document.getElementById('voice-trigger-btn');
    mainMicIcon      = document.getElementById('main-mic-icon');
    handsfreeBtn     = document.getElementById('handsfree-btn');
    handsfreeLabel   = document.getElementById('handsfree-status-label');
    orbHitbox        = document.getElementById('orb-hitbox');
    cmdInput         = document.getElementById('command-input');
    sendBtn          = document.getElementById('send-command-btn');
    statusText       = document.getElementById('system-status-text');
    statusDot        = document.getElementById('status-indicator');

    setupEventListeners();

    // Auto-start VAD on first interaction
    document.body.addEventListener('click', startHandsFreeVAD, { once: true });
    document.body.addEventListener('keydown', startHandsFreeVAD, { once: true });
    setTimeout(startHandsFreeVAD, 800);
  }

  function refreshIcons() {
    if (window.lucide && lucide.createIcons) lucide.createIcons();
  }

  function setAgentState(state, customSubtitle = null) {
    if (isMuted && state !== 'muted') state = 'muted';

    if (typeof VisionOrb !== 'undefined' && VisionOrb.setState) VisionOrb.setState(state);

    if (state === 'muted') {
      if (statusText) statusText.textContent = 'MUTED (NOT LISTENING)';
      if (statusDot) statusDot.className = 'status-dot muted';
      if (orbHitbox) orbHitbox.classList.add('muted');
      if (micBtn) { micBtn.classList.add('muted'); micBtn.classList.remove('listening'); }
      if (mainMicIcon) mainMicIcon.innerHTML = `<i data-lucide="mic-off" class="icon-md"></i>`;
    } else if (state === 'idle') {
      if (statusText) statusText.textContent = 'ONLINE';
      if (statusDot) statusDot.className = 'status-dot';
      if (orbHitbox) orbHitbox.classList.remove('muted');
      if (micBtn) { micBtn.classList.remove('muted'); micBtn.classList.remove('listening'); }
      if (mainMicIcon) mainMicIcon.innerHTML = `<i data-lucide="mic" class="icon-md"></i>`;
    } else if (state === 'listening') {
      if (statusText) statusText.textContent = 'RECORDING SPEECH';
      if (statusDot) statusDot.className = 'status-dot';
      if (orbHitbox) orbHitbox.classList.remove('muted');
      if (micBtn) { micBtn.classList.remove('muted'); micBtn.classList.add('listening'); }
      if (mainMicIcon) mainMicIcon.innerHTML = `<i data-lucide="mic" class="icon-md"></i>`;
    } else if (state === 'thinking') {
      if (statusText) statusText.textContent = 'NEURAL REASONING';
      if (statusDot) statusDot.className = 'status-dot busy';
      if (orbHitbox) orbHitbox.classList.remove('muted');
      if (micBtn) { micBtn.classList.remove('muted'); micBtn.classList.remove('listening'); }
    } else if (state === 'executing') {
      if (statusText) statusText.textContent = 'EXECUTING ACTIONS';
      if (statusDot) statusDot.className = 'status-dot busy';
      if (orbHitbox) orbHitbox.classList.remove('muted');
    } else if (state === 'speaking') {
      if (statusText) statusText.textContent = 'VOICE ACTIVE';
      if (statusDot) statusDot.className = 'status-dot';
      if (orbHitbox) orbHitbox.classList.remove('muted');
      if (micBtn) micBtn.classList.remove('muted');
    }
    refreshIcons();
  }

  function setupEventListeners() {
    if (muteBtn) muteBtn.addEventListener('click', toggleMute);
    if (handsfreeBtn) handsfreeBtn.addEventListener('click', toggleHandsFree);

    if (orbHitbox) {
      orbHitbox.addEventListener('click', () => {
        if (isMuted) toggleMute();
        else if (!handsFreeEnabled) toggleManualRecord();
      });
    }

    if (micBtn) {
      micBtn.addEventListener('click', (e) => {
        e.preventDefault();
        toggleManualRecord();
      });
    }

    document.addEventListener('keydown', (e) => {
      // Ignore all global hotkeys when typing inside any input, textarea, or editable element
      const active = document.activeElement;
      const isTyping = active && (
        active.tagName === 'INPUT' ||
        active.tagName === 'TEXTAREA' ||
        active.isContentEditable ||
        active.tagName === 'SELECT'
      );
      if (isTyping) return;

      if ((e.key === 'm' || e.key === 'M') && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        toggleMute();
      } else if (e.code === 'Space' && !isProcessing && !e.ctrlKey && !e.altKey && !e.metaKey) {
        const voicePage = document.getElementById('page-voice');
        if (voicePage && voicePage.classList.contains('active')) {
          e.preventDefault();
          toggleManualRecord();
        }
      }
    });

    if (cmdInput) {
      cmdInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); executeCommandText(); }
      });
    }
    if (sendBtn) {
      sendBtn.addEventListener('click', (e) => { e.preventDefault(); executeCommandText(); });
    }

    const copyTranscriptsBtn = document.getElementById('copy-transcripts-btn');
    if (copyTranscriptsBtn) {
      copyTranscriptsBtn.addEventListener('click', (e) => {
        e.preventDefault();
        VisionTranscript.copyAsJSON();
      });
    }
  }

  // ── Manual Push-to-Talk ──
  async function toggleManualRecord() {
    if (isMuted) { toggleMute(); return; }

    if (isManualRecording || (mediaRecorder && mediaRecorder.state === 'recording')) {
      isManualRecording = false;
      if (micBtn) micBtn.classList.remove('listening');
      setAgentState('thinking');
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        try { mediaRecorder.stop(); } catch(e){}
      }
      return;
    }

    if (VisionOrb.getState() === 'speaking' || speechTimeout || (typeof VisionTranscript !== 'undefined' && VisionTranscript.isLiveStreaming())) {
      if (speechTimeout) { clearTimeout(speechTimeout); speechTimeout = null; }
      if (typeof VisionTranscript !== 'undefined') VisionTranscript.cancelLiveTranscript();
      fetch(`${API_BASE}/api/audio/stop`, { method: 'POST' }).catch(() => {});
    }

    try {
      if (!micStream) {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
        });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        const source = audioContext.createMediaStreamSource(micStream);
        source.connect(analyser);
      }
      setupMediaRecorder();

      isManualRecording = true;
      recordedChunks = [];
      if (mediaRecorder) {
        if (mediaRecorder.state === 'recording') { try { mediaRecorder.stop(); } catch(e){} }
        mediaRecorder.start(100);
      }
      setAgentState('listening');
      if (micBtn) micBtn.classList.add('listening');
      statusText.textContent = 'LISTENING (CLICK MIC TO SEND)';
    } catch (err) {
      setAgentState('idle');
    }
  }

  // ── Mute Toggle ──
  function toggleMute() {
    isMuted = !isMuted;

    if (isMuted) {
      if (muteBtn) muteBtn.classList.add('muted-state');
      if (muteBtn) muteBtn.classList.remove('active-hud');
      if (muteIconContainer) muteIconContainer.innerHTML = `<i data-lucide="mic-off" class="icon-sm"></i>`;
      if (muteLabel) muteLabel.textContent = 'MUTED: ON';

      if (typeof VisionTranscript !== 'undefined') VisionTranscript.cancelLiveTranscript();
      fetch(`${API_BASE}/api/audio/stop`, { method: 'POST' }).catch(() => {});

      if (micStream) micStream.getAudioTracks().forEach(track => track.enabled = false);
      if (mediaRecorder && mediaRecorder.state === 'recording') { try { mediaRecorder.stop(); } catch(e){} }
      recordedChunks = [];
      isUserSpeaking = false;
      isManualRecording = false;
      if (micBtn) micBtn.classList.remove('listening');
      setAgentState('muted');
      VisionTranscript.logAction('tool', 'Microphone Muted', 'Audio input paused.');
    } else {
      if (muteBtn) muteBtn.classList.remove('muted-state');
      if (muteBtn) muteBtn.classList.add('active-hud');
      if (muteIconContainer) muteIconContainer.innerHTML = `<i data-lucide="mic" class="icon-sm"></i>`;
      if (muteLabel) muteLabel.textContent = 'MUTE: OFF';

      if (micStream) {
        micStream.getAudioTracks().forEach(track => track.enabled = true);
      } else if (handsFreeEnabled) {
        startHandsFreeVAD();
      }
      setAgentState('idle');
      VisionTranscript.logAction('tool', 'Microphone Unmuted', 'Audio input active.');
    }
    refreshIcons();
  }

  function toggleHandsFree() {
    handsFreeEnabled = !handsFreeEnabled;

    if (handsFreeEnabled) {
      if (handsfreeBtn) { handsfreeBtn.classList.remove('off'); handsfreeBtn.classList.add('accent-green'); }
      if (handsfreeLabel) handsfreeLabel.textContent = 'HANDS-FREE VAD: ON';
      startHandsFreeVAD();
      VisionTranscript.logAction('tool', 'Hands-Free VAD', 'Auto voice detection active.');
    } else {
      if (handsfreeBtn) { handsfreeBtn.classList.add('off'); handsfreeBtn.classList.remove('accent-green'); }
      if (handsfreeLabel) handsfreeLabel.textContent = 'HANDS-FREE VAD: OFF';
      stopHandsFreeVAD();
      setAgentState('idle');
      VisionTranscript.logAction('tool', 'Hands-Free VAD', 'Manual Push-to-Talk active.');
    }
    refreshIcons();
  }

  // ── Hands-Free VAD Engine ──
  async function startHandsFreeVAD() {
    if (micStream || isProcessing || isMuted || !handsFreeEnabled) return;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      audioContext = new (window.AudioContext || window.webkitAudioContext)();

      const highpass = audioContext.createBiquadFilter();
      highpass.type = 'highpass';
      highpass.frequency.value = 120;

      const lowpass = audioContext.createBiquadFilter();
      lowpass.type = 'lowpass';
      lowpass.frequency.value = 3400;

      analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.4;

      const source = audioContext.createMediaStreamSource(micStream);
      source.connect(highpass);
      highpass.connect(lowpass);
      lowpass.connect(analyser);

      setupMediaRecorder();
      startVADLoop();
      setAgentState('idle');
    } catch (err) {
      setAgentState('idle');
    }
  }

  function stopHandsFreeVAD() {
    if (vadCheckInterval) { clearInterval(vadCheckInterval); vadCheckInterval = null; }
    if (mediaRecorder && mediaRecorder.state === 'recording') { try { mediaRecorder.stop(); } catch(e){} }
    isUserSpeaking = false;
    isManualRecording = false;
    consecutiveSpeechFrames = 0;
    if (micBtn) micBtn.classList.remove('listening');
  }

  function setupMediaRecorder() {
    if (!micStream) return;
    try {
      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) mimeType = 'audio/webm;codecs=opus';
      else if (MediaRecorder.isTypeSupported('audio/webm')) mimeType = 'audio/webm';
      else if (MediaRecorder.isTypeSupported('audio/ogg')) mimeType = 'audio/ogg';

      mediaRecorder = new MediaRecorder(micStream, { mimeType });
      recordedChunks = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) recordedChunks.push(e.data);
      };
      mediaRecorder.onstop = onRecordingFinalized;
    } catch (e) {
      console.warn('[Recorder] Setup error:', e);
    }
  }

  function startVADLoop() {
    if (vadCheckInterval) clearInterval(vadCheckInterval);
    const buffer = new Float32Array(analyser.fftSize);
    const audioFreqData = new Uint8Array(32);

    vadCheckInterval = setInterval(() => {
      if (!analyser || !handsFreeEnabled || isMuted || isManualRecording) return;

      analyser.getFloatTimeDomainData(buffer);
      analyser.getByteFrequencyData(audioFreqData);
      VisionOrb.setAudioData(audioFreqData);

      let sum = 0;
      for (let i = 0; i < buffer.length; i++) sum += buffer[i] * buffer[i];
      const rms = Math.sqrt(sum / buffer.length);
      const now = Date.now();

      if (!isUserSpeaking && VisionOrb.getState() !== 'speaking' && !isProcessing) {
        ambientNoiseFloor = ambientNoiseFloor * 0.96 + rms * 0.04;
      }

      // Check if VISION is currently thinking, executing, or speaking
      const isAgentActive = (VisionOrb.getState() === 'speaking' || VisionOrb.getState() === 'thinking' || VisionOrb.getState() === 'executing' || speechTimeout !== null || isProcessing);

      // When VISION is speaking or generating, use a high threshold and more frames to prevent speaker bleed from triggering VAD
      const dynamicThreshold = isAgentActive ? Math.max(0.18, ambientNoiseFloor * 7.0) : Math.max(0.038, Math.min(0.09, ambientNoiseFloor * 3.2));
      const requiredFrames = isAgentActive ? 8 : REQUIRED_SPEECH_FRAMES; // Require 320ms of deliberate loud speech to interrupt

      if (rms > dynamicThreshold) {
        consecutiveSpeechFrames++;
        lastSpeechTime = now;

        // Intentional Barge-in: only if user deliberately speaks loudly over VISION for 8+ frames
        if (isAgentActive && consecutiveSpeechFrames >= requiredFrames) {
          if (speechTimeout) { clearTimeout(speechTimeout); speechTimeout = null; }
          if (typeof VisionTranscript !== 'undefined') VisionTranscript.cancelLiveTranscript();
          fetch(`${API_BASE}/api/audio/stop`, { method: 'POST' }).catch(() => {});
          isProcessing = false;
          setAgentState('listening');
        }

        if (consecutiveSpeechFrames >= requiredFrames && !isUserSpeaking) {
          isProcessing = false;
          isUserSpeaking = true;
          speechStartTime = now;
          setAgentState('listening');

          recordedChunks = [];
          if (mediaRecorder) {
            if (mediaRecorder.state === 'recording') { try { mediaRecorder.stop(); } catch(e){} }
            try { mediaRecorder.start(100); } catch(e){}
          }
        }
      } else {
        consecutiveSpeechFrames = 0;
        if (isUserSpeaking) {
          const silenceDuration = now - lastSpeechTime;
          const totalSpeechDuration = now - speechStartTime;
          const adaptiveSilenceTimeout = (totalSpeechDuration > 2200) ? 1200 : 850;

          if (silenceDuration >= adaptiveSilenceTimeout) {
            isUserSpeaking = false;
            if (totalSpeechDuration >= MIN_SPEECH_DURATION_MS) {
              setAgentState('thinking');
              if (mediaRecorder && mediaRecorder.state === 'recording') { try { mediaRecorder.stop(); } catch(e){} }
            } else {
              recordedChunks = [];
              if (mediaRecorder && mediaRecorder.state === 'recording') { try { mediaRecorder.stop(); } catch(e){} }
              setAgentState('idle');
            }
          }
        }
      }
    }, 40);
  }

  async function onRecordingFinalized() {
    if (recordedChunks.length === 0 || isMuted) {
      if (!isProcessing) setAgentState(isMuted ? 'muted' : 'idle');
      return;
    }
    const mimeType = mediaRecorder?.mimeType || 'audio/webm';
    const blob = new Blob(recordedChunks, { type: mimeType });
    recordedChunks = [];

    // Reject tiny audio chunks (under 2KB is noise/empty)
    if (blob.size < 2000) {
      if (!isProcessing) setAgentState(isMuted ? 'muted' : 'idle');
      return;
    }

    isProcessing = true;
    const formData = new FormData();
    const filename = mimeType.includes('ogg') ? 'voice.ogg' : 'voice.webm';
    formData.append('file', blob, filename);

    try {
      setAgentState('thinking');
      const res = await fetch(`${API_BASE}/api/audio/transcribe`, { method: 'POST', body: formData });
      const data = await res.json();
      const text = (data.text || '').trim();

      // Whisper Hallucination Filter
      const noiseHallucinations = [
        'thank you', 'thank you.', 'thanks', 'thanks.', 'thanks for watching', 'thanks for watching.',
        'you', 'you.', 'subtitles by', 'amara.org', 'bye', 'bye.', 'goodbye', 'goodbye.', 'okay', 'okay.',
        'ok', 'ok.', 'silence', '...', '.', 'mm', 'uh', 'um', 'yeah', 'yeah.', 'yep', 'yep.'
      ];
      const cleanLower = text.toLowerCase().replace(/[^\w\s]/g, '').trim();

      if (text.length >= 3 && !noiseHallucinations.includes(text.toLowerCase()) && !noiseHallucinations.includes(cleanLower)) {
        VisionTranscript.logTranscript('user', 'You (Spoken)', text);
        await sendToVision(text);
      } else {
        isProcessing = false;
        setAgentState(isMuted ? 'muted' : 'idle');
      }
    } catch (err) {
      isProcessing = false;
      setAgentState(isMuted ? 'muted' : 'idle');
    }
  }

  async function executeCommandText() {
    const text = cmdInput.value.trim();
    if (!text) return;
    cmdInput.value = '';

    if (VisionOrb.getState() === 'speaking' || speechTimeout || (typeof VisionTranscript !== 'undefined' && VisionTranscript.isLiveStreaming())) {
      if (speechTimeout) { clearTimeout(speechTimeout); speechTimeout = null; }
      if (typeof VisionTranscript !== 'undefined') VisionTranscript.cancelLiveTranscript();
      fetch(`${API_BASE}/api/audio/stop`, { method: 'POST' }).catch(() => {});
    }

    VisionTranscript.logTranscript('user', 'You (Typed)', text);
    await sendToVision(text);
  }

  async function sendToVision(userMessage) {
    isProcessing = true;
    setAgentState('thinking');

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMessage,
          session_id: 'vision_hud_session',
          synthesize_voice: true
        })
      });

      const data = await res.json();
      const responseText = data.response || data.detail || 'Action completed.';

      // Unblock processing immediately so new microphone speech can be detected
      isProcessing = false;
      setAgentState('speaking');

      // Live word-by-word streaming synchronization with spoken voice
      VisionTranscript.streamSpokenText(responseText, {
        onWord: () => {
          if (VisionOrb.getState() !== 'speaking' && !isMuted && !isUserSpeaking) {
            setAgentState('speaking');
          }
        },
        onComplete: () => {
          if (VisionOrb.getState() === 'speaking' && !isUserSpeaking) {
            setAgentState(isMuted ? 'muted' : 'idle');
          }
        }
      });

    } catch (err) {
      if (typeof VisionTranscript !== 'undefined') {
        VisionTranscript.cancelLiveTranscript();
        VisionTranscript.logTranscript('ai', 'VISION', `⚠️ Request failed: ${err.message}. Ensure VISION server is running.`);
      }
      setAgentState(isMuted ? 'muted' : 'idle');
      isProcessing = false;
    }
  }

  return { init, setAgentState, toggleMute, toggleHandsFree };
})();
