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
  if (header.classList.contains('as-header--lots')) {
    const mobile = window.matchMedia('(max-width: 800px)');
    const menu = document.createElement('button');
    menu.type = 'button';
    menu.className = 'lots-menu-toggle';
    menu.textContent = 'Menu';
    menu.setAttribute('aria-expanded', 'false');
    menu.setAttribute('aria-controls', 'lots-mobile-options');
    const main = document.createElement('div');
    main.className = 'lots-mobile-main';
    const panel = document.createElement('section');
    panel.id = 'lots-mobile-options';
    panel.className = 'lots-mobile-options';
    panel.setAttribute('aria-label', 'Navigation and search options');
    panel.hidden = true;
    const heading = document.createElement('h2');
    heading.textContent = 'Navigation & search options';
    panel.append(heading);
    header.querySelector('.as-top').append(menu);
    header.append(main, panel);
    const placements = [
      ['#searchBox', main], ['.as-page-controls', main],
      ['.as-utilities', panel], ['#featuredSearches', panel],
      ['#refinedSearch', panel], ['.snapshot-label', panel]
    ].map(([selector, destination]) => {
      const node = header.querySelector(selector);
      const home = document.createComment('Mobile header restore point');
      node.before(home);
      return {node, home, destination};
    });
    const closeMenu = () => {
      panel.hidden = true;
      menu.setAttribute('aria-expanded', 'false');
    };
    menu.addEventListener('click', () => {
      panel.hidden = !panel.hidden;
      menu.setAttribute('aria-expanded', String(!panel.hidden));
    });
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        closeMenu(); menu.focus({preventScroll:true});
      }
    });
    const arrange = () => {
      const focused = document.activeElement;
      closeMenu();
      placements.forEach(({node, home, destination}) => {
        if (mobile.matches) destination.append(node);
        else home.after(node);
      });
      if (focused && header.contains(focused) && focused !== document.activeElement) {
        if (mobile.matches && panel.contains(focused)) menu.focus({preventScroll:true});
        else focused.focus({preventScroll:true});
      }
    };
    arrange();
    mobile.addEventListener('change', arrange);
    // Keep an active secondary filter visible even while its panel is closed.
    const filter = header.querySelector('#wantedFilterButton');
    const showFilterState = () => {
      const active = filter.getAttribute('aria-pressed') === 'true';
      menu.textContent = active ? 'Menu •' : 'Menu';
      menu.setAttribute('aria-label', active ? 'Menu, refined search on' : 'Menu');
    };
    new MutationObserver(showFilterState).observe(filter, {attributes:true, attributeFilter:['aria-pressed']});
    showFilterState();
  }
  const updateOffset = () => {
    const sticky = getComputedStyle(header).position === 'sticky';
    document.documentElement.style.setProperty('--as-header-offset', `${sticky ? header.offsetHeight : 0}px`);
  };
  updateOffset();
  if ('ResizeObserver' in window) new ResizeObserver(updateOffset).observe(header);
  window.addEventListener('resize', updateOffset, { passive: true });
})();
