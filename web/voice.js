/* Voice behind ONE small interface:  Voice.listen(lang) -> Promise<text>,  Voice.speak(text, lang).
 *
 * Providers:
 *   browser (default) - Web Speech API (SpeechRecognition hi-IN/en-IN + speechSynthesis). No key.
 *   verbx             - chosen by the SERVER (env VOICE_PROVIDER=verbx). The browser never sees
 *                       the API key: it only calls our own backend /api/voice/*.
 * If VerbX is missing, errors or times out we fall back to the browser provider and show a notice.
 * The text box always works, even with no voice support at all.
 */
const Voice = (() => {
  const BCP47 = { hi: 'hi-IN', en: 'en-IN' };
  let config = { provider: 'browser' };
  let fellBack = false;
  let muted = false;
  let notify = () => {};

  // ---------------- browser provider (Web Speech API) ----------------
  const browser = {
    canListen() { return !!(window.SpeechRecognition || window.webkitSpeechRecognition); },

    listen(lang) {
      return new Promise((resolve, reject) => {
        const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!Rec) return reject(new Error('not-supported'));
        const rec = new Rec();
        rec.lang = BCP47[lang] || 'hi-IN';
        rec.interimResults = false;
        rec.maxAlternatives = 1;
        let done = false;
        rec.onresult = (e) => { done = true; resolve(e.results[0][0].transcript); };
        rec.onerror = (e) => { if (!done) { done = true; reject(new Error(e.error || 'error')); } };
        rec.onend = () => { if (!done) reject(new Error('no-speech')); };
        rec.start();
      });
    },

    speak(text, lang) {
      if (!('speechSynthesis' in window) || !text) return Promise.resolve();
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = BCP47[lang] || 'hi-IN';
      u.rate = 0.95;
      const voices = speechSynthesis.getVoices();
      u.voice = voices.find(v => v.lang === u.lang) || voices.find(v => v.lang.startsWith(lang)) || null;
      return new Promise((resolve) => { u.onend = resolve; u.onerror = resolve; speechSynthesis.speak(u); });
    },

    stop() { if ('speechSynthesis' in window) speechSynthesis.cancel(); },
  };

  // ================================================================
  // VerbX provider - STUB. Calls OUR backend, which holds the key.
  // The backend adapter is not implemented until the VerbX API docs
  // are provided, so these calls fail and we fall back to the browser.
  // ================================================================
  const verbx = {
    async speak(text, lang) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 5000);   // timeout -> fallback
      try {
        const r = await fetch('/api/voice/tts', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, lang }), signal: ctrl.signal,
        });
        if (!r.ok) throw new Error('verbx tts ' + r.status);
        const audio = new Audio(URL.createObjectURL(await r.blob()));
        await audio.play();
      } finally { clearTimeout(timer); }
    },
    async listen(lang) {
      // TODO(VerbX): record audio with MediaRecorder and POST it to /api/voice/stt?lang=...
      throw new Error('verbx listen not implemented (stub)');
    },
    stop() {},
  };

  async function use(method, ...args) {
    if (config.provider === 'verbx' && !fellBack) {
      try { return await verbx[method](...args); }
      catch (err) {
        fellBack = true;
        notify('VerbX voice unavailable - using browser voice. · VerbX उपलब्ध नहीं, ब्राउज़र की आवाज़ इस्तेमाल हो रही है।');
      }
    }
    return browser[method](...args);
  }

  return {
    init(cfg, onNotice) {
      config = cfg || config;
      notify = onNotice || notify;
      if (config.provider === 'verbx' && config.notice) { fellBack = true; notify(config.notice); }
    },
    listen: (lang) => use('listen', lang),
    speak: (text, lang) => (muted ? Promise.resolve() : use('speak', text, lang)),
    stop: () => browser.stop(),
    canListen: () => browser.canListen(),
    setMuted(m) { muted = m; if (m) browser.stop(); },
    isMuted: () => muted,
    provider: () => (fellBack ? 'browser' : config.provider),
  };
})();
