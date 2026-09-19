// Keep in-page destinations clear of the shared header when it wraps or zooms.
(() => {
  const header = document.querySelector('body > .as-header');
  if (!header) return;
  // Move the actual nodes so mobile reading and Tab order match the rows.
  if (header.classList.contains('as-header--map')) {
    const mobile = window.matchMedia('(max-width: 800px)');
    const row = header.querySelector('.as-bottom');
    const utilities = row.querySelector('.as-utilities');
    const controls = row.querySelector('.as-page-controls');
    const orderMapRows = () => {
      const first = mobile.matches ? utilities : controls;
      if (row.firstElementChild === first) return;
      const focused = document.activeElement;
      row.prepend(first);
      if (focused && row.contains(focused) && document.activeElement !== focused) {
        focused.focus({ preventScroll: true });
      }
    };
    orderMapRows();
    mobile.addEventListener('change', orderMapRows);
  }
  const updateOffset = () => {
    const sticky = getComputedStyle(header).position === 'sticky';
    document.documentElement.style.setProperty('--as-header-offset', `${sticky ? header.offsetHeight : 0}px`);
  };
  updateOffset();
  if ('ResizeObserver' in window) new ResizeObserver(updateOffset).observe(header);
  window.addEventListener('resize', updateOffset, { passive: true });
})();
