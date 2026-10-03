// Keep in-page destinations clear of the shared header when it wraps or zooms.
(() => {
  const header = document.querySelector('body > .as-header');
  if (!header) return;
  const isMap = header.classList.contains('as-header--map');
  if (isMap || header.classList.contains('as-header--lots')) {
    const mobile = window.matchMedia('(max-width: 800px)');
    const menu = document.createElement('button');
    menu.type = 'button';
    menu.className = 'lots-menu-toggle';
    menu.textContent = 'Menu';
    menu.setAttribute('aria-expanded', 'false');
    menu.setAttribute('aria-controls', isMap ? 'map-mobile-options' : 'lots-mobile-options');
    const main = document.createElement('div');
    main.className = 'lots-mobile-main';
    const panel = document.createElement('section');
    panel.id = isMap ? 'map-mobile-options' : 'lots-mobile-options';
    panel.className = 'lots-mobile-options';
    panel.setAttribute('aria-label', isMap ? 'Navigation and snapshot' : 'Navigation and search options');
    panel.hidden = true;
    const heading = document.createElement('h2');
    heading.textContent = isMap ? 'Navigation & snapshot' : 'Navigation & search options';
    panel.append(heading);
    header.querySelector('.as-top').append(menu);
    header.append(main, panel);
    const placements = (isMap ? [
      ['.as-description', main], ['.as-page-controls', main],
      ['.as-utilities', panel], ['.snapshot-label', panel]
    ] : [
      ['#searchBox', main], ['.as-page-controls', main],
      ['.as-utilities', panel], ['#featuredSearches', panel],
      ['#refinedSearch', panel], ['.snapshot-label', panel]
    ]).map(([selector, destination]) => {
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
    if (filter) {
      const showFilterState = () => {
        const active = filter.getAttribute('aria-pressed') === 'true';
        menu.textContent = active ? 'Menu •' : 'Menu';
        menu.setAttribute('aria-label', active ? 'Menu, refined search on' : 'Menu');
      };
      new MutationObserver(showFilterState).observe(filter, {attributes:true, attributeFilter:['aria-pressed']});
      showFilterState();
    }
  }
  const updateOffset = () => {
    const sticky = getComputedStyle(header).position === 'sticky';
    document.documentElement.style.setProperty('--as-header-offset', `${sticky ? header.offsetHeight : 0}px`);
  };
  updateOffset();
  if ('ResizeObserver' in window) new ResizeObserver(updateOffset).observe(header);
  window.addEventListener('resize', updateOffset, { passive: true });
})();
