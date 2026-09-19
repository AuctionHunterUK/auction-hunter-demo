// Keep in-page destinations clear of the shared header when it wraps or zooms.
(() => {
  const header = document.querySelector('body > .as-header');
  if (!header) return;
  const updateOffset = () => {
    const sticky = getComputedStyle(header).position === 'sticky';
    document.documentElement.style.setProperty('--as-header-offset', `${sticky ? header.offsetHeight : 0}px`);
  };
  updateOffset();
  if ('ResizeObserver' in window) new ResizeObserver(updateOffset).observe(header);
  window.addEventListener('resize', updateOffset, { passive: true });
})();
