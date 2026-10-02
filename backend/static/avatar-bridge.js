/* SDK is attached only after successful init. No SDK download or cloud call at startup. */
class AvatarBridge {
  constructor() { this.sdk = null; this.buffer = ''; this.started = false; }
  get active() { return !!this.sdk; }
  attach(sdk) {
    for (const method of ['speak', 'listen', 'think', 'interactiveidle', 'destroy']) {
      if (typeof sdk?.[method] !== 'function') throw new Error('数字人 SDK 缺少方法：' + method);
    }
    this.detach();
    this.sdk = sdk;
    const container = document.getElementById('avatar-container');
    if (container) container.style.display = 'block';
    const fallback = document.querySelector('#dm-panel .dm-stage');
    if (fallback) fallback.style.display = 'none';
    this.status('魔珐星云数字人已连接');
  }
  status(text) { const el = document.getElementById('avatar-status'); if (el) el.textContent = text; }
  reset() { this.buffer = ''; this.started = false; }
  detach() {
    const sdk = this.sdk;
    this.sdk = null; this.reset();
    try { sdk?.destroy(); } catch (_) { /* Always restore the fallback UI. */ }
    const container = document.getElementById('avatar-container');
    if (container) container.style.display = 'none';
    const fallback = document.querySelector('#dm-panel .dm-stage');
    if (fallback) fallback.style.display = '';
    this.status('小伴在这里，随时听您说');
  }
  speak(text, end) {
    // Treat model output as text, never as untrusted SSML commands.
    const escaped = String(text).replace(/[&<>]/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;'}[c]));
    this.sdk.speak(escaped, !this.started, end);
    this.started = !end;
  }
  handle(event) {
    if (!this.sdk) return;
    try {
      switch (event.type) {
        case 'emotion': this.reset(); this.sdk.listen(); break;
        case 'thinking': this.sdk.think(); break;
        case 'reply_delta':
          this.buffer += event.text || '';
          // Retain at least one fragment so the final speak is never empty.
          if (this.buffer.length > 48) {
            const split = this.buffer.search(/[。！？；\n]/);
            const end = split >= 0 && split < this.buffer.length - 1 ? split + 1 : this.buffer.length - 24;
            this.speak(this.buffer.slice(0, end), false);
            this.buffer = this.buffer.slice(end);
          }
          break;
        case 'reply_done': {
          const text = this.buffer || (!this.started ? event.reply || '' : '');
          if (text) this.speak(text, true);
          this.reset();
          break;
        }
        case 'reminder_due': case 'care':
          this.reset(); this.sdk.interactiveidle();
          if (event.message) this.speak(event.message, true);
          break;
        case 'interrupted': case 'interrupt': case 'error':
          this.reset(); this.sdk.interactiveidle(); break;
      }
    } catch (error) {
      this.detach();
      this.status('数字人连接异常，已恢复文字与语音功能');
      console.warn('Avatar integration:', error.message);
    }
  }
}
window.avatarBridge = new AvatarBridge();
window.addEventListener('beforeunload', () => window.avatarBridge.detach());
