// One persisted text scale for all modules and both conversation modes.
(() => {
  const key = 'ylb_font_percent';
  const min = 70, max = 180, step = 10;
  let percent = 100;
  try {
    const saved = localStorage.getItem(key);
    percent = saved !== null ? Number(saved) : localStorage.getItem('ylb_bigfont') === '1' ? 120 : 100;
  } catch (_) { /* Controls also work when browser storage is unavailable. */ }

  function apply(value, persist = true) {
    percent = Number.isFinite(value) ? Math.min(max, Math.max(min, Math.round(value / step) * step)) : 100;
    document.documentElement.style.setProperty('--font-scale', String(percent / 100));
    const smaller = document.getElementById('font-smaller');
    const larger = document.getElementById('font-larger');
    const label = document.getElementById('font-percent');
    if (smaller) smaller.disabled = percent === min;
    if (larger) larger.disabled = percent === max;
    if (label) label.textContent = `${percent}%`;
    if (persist) {
      try { localStorage.setItem(key, String(percent)); } catch (_) { /* Keep this session usable. */ }
    }
  }
  apply(percent, false);
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('font-smaller').onclick = () => apply(percent - step);
    document.getElementById('font-larger').onclick = () => apply(percent + step);
    document.getElementById('font-reset').onclick = () => apply(100);
    apply(percent, false);
  });
})();
