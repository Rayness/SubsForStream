/* Shared browser recognizer. No offline transcript buffer, no overlapping sessions. */
class LiveSpeech {
  constructor({socket, language, state, text}) {
    Object.assign(this, {socket, language, state, text});
    this.wanted = false;
    this.rec = null;
    this.timer = null;
    this.failures = 0;
    this.generation = 0;
    this.lastText = '';
    socket.on('disconnect', () => {
      this.cancelSession();
      if (this.wanted) state('waiting', 'Нет связи с сервером…');
    });
    socket.on('connect', () => { if (this.wanted) this.claim(); });
    this.heartbeat = setInterval(() => {
      if (this.wanted && socket.connected) this.claim(false);
    }, 3000);
    window.addEventListener('pagehide', () => this.stop());
  }
  toggle() { this.wanted ? this.stop() : this.start(); }
  start() {
    if (this.wanted) return;
    if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) {
      this.state('error', 'Распознавание недоступно. Откройте Chrome или используйте локальный режим.');
      return;
    }
    this.wanted = true;
    this.failures = 0;
    this.state('waiting', 'Подключение…');
    if (this.socket.connected) this.claim();
  }
  claim(start = true) {
    const generation = this.generation;
    this.socket.timeout(3000).emit('claim', (error, response) => {
      if (!this.wanted || generation !== this.generation) return;
      if (error) {
        if (start) this.timer = setTimeout(() => this.claim(), 1000);
        return;
      }
      if (!response?.ok) {
        this.stop('Другой микрофон уже работает. Остановите его перед переключением.');
        return;
      }
      if (start && !this.rec) this.begin();
    });
  }
  cancelSession() {
    ++this.generation;
    clearTimeout(this.timer);
    const rec = this.rec;
    this.rec = null;
    if (rec) {
      rec.onend = rec.onerror = rec.onresult = rec.onstart = null;
      try { rec.abort(); } catch (_) {}
    }
    this.lastText = '';
  }
  stop(message = 'Остановлено') {
    this.wanted = false;
    this.cancelSession();
    if (this.socket.connected) this.socket.emit('release');
    this.state('idle', message);
  }
  setLanguage() {
    if (this.rec && this.rec.lang !== this.language()) {
      this.cancelSession();
      if (this.wanted && this.socket.connected) this.claim();
    }
  }
  begin() {
    if (!this.wanted || !this.socket.connected || this.rec) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = this.rec = new SR();
    const generation = this.generation;
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = this.language();
    rec.maxAlternatives = 1;
    let retryDelay = 0;
    rec.onstart = () => this.state('listening', 'Слушаю • браузер');
    rec.onresult = event => {
      if (!this.wanted || generation !== this.generation || !this.socket.connected) return;
      this.failures = 0;
      let interim = '';
      // Finals precede the next interim, so old text cannot overwrite newer words.
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        const result = event.results[i];
        if (result.isFinal) this.send(result[0].transcript.trim(), true);
        else interim += result[0].transcript;
      }
      if (interim.trim()) this.send(interim.trim(), false);
    };
    rec.onerror = event => {
      if (['not-allowed', 'service-not-allowed', 'audio-capture', 'language-not-supported'].includes(event.error)) {
        this.stop();
        this.state('error', 'Ошибка микрофона/распознавания: ' + event.error);
        return;
      }
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        retryDelay = Math.min(5000, 250 * 2 ** Math.min(this.failures++, 5));
        this.state('waiting', 'Переподключение распознавания: ' + event.error);
      }
    };
    rec.onend = () => {
      if (generation !== this.generation) return;
      this.rec = null;
      this.lastText = '';
      if (this.wanted && this.socket.connected) this.timer = setTimeout(() => this.begin(), retryDelay);
    };
    try { rec.start(); }
    catch (error) { this.stop(); this.state('error', error.message); }
  }
  send(text, final) {
    if (!text || (!final && text === this.lastText)) return;
    this.lastText = final ? '' : text;
    this.text(text, final);
    // A disconnect must not replay old captions on reconnect.
    if (this.socket.connected) this.socket.emit('transcript', {text, final});
  }
}
