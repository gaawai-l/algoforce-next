// Shared navigation for all throwaway portfolio and market layouts.
function appShell(content, active) {
  const icons = {
    overview: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 10h18M10 10v11"/>',
    cycles: '<path d="M20 9a8 8 0 1 0 0 7M20 3v6h-6"/>',
    risk: '<path d="M2 13h5l3-8 5 15 3-7h4"/>',
    market: '<circle cx="12" cy="12" r="7"/><path d="M12 2v5m0 10v5M2 12h5m10 0h5"/>'
  };
  const links = [
    ['overview', 'Overview', 'index.html?variant=A'],
    ['cycles', 'Wheel cycles', 'index.html?variant=B'],
    ['risk', 'Risk exposure', 'index.html?variant=C'],
    ['market', 'Market intelligence', 'market-prototype.html?tab=td9']
  ];
  return `<div class="app-shell"><button class="shell-menu" data-shell-menu aria-label="Open navigation" aria-expanded="false" aria-controls="workspace-sidebar">☰ <span>WHEELHOUSE</span></button><button class="shell-scrim" data-shell-close aria-label="Close navigation"></button><aside id="workspace-sidebar" class="workspace-sidebar"><a class="shell-brand" href="index.html?variant=A"><span><svg viewBox="0 0 24 24" width="23" height="23" fill="none" aria-hidden="true"><path d="M3 5L7 19L12 10L17 19L21 5M8 5H16" stroke="currentColor" stroke-width="2"/></svg></span>WHEELHOUSE</a><div class="shell-label">CONTROL DECK</div><nav aria-label="Workspace">${links.map(([key,label,href])=>`<a href="${href}" class="shell-link ${active===key?'active':''}" ${active===key?'aria-current="page"':''}><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${icons[key]}</svg>${label}</a>`).join('')}</nav><div class="shell-footer"><div class="shell-label">DATA SOURCE</div><p>moomoo Singapore</p><small>Demo account / Offline</small><div class="shell-account"><span>G</span><div>Personal portfolio<small>USD base currency</small></div></div></div></aside><div class="app-content">${content}</div></div>`;
}
document.addEventListener('click', event => {
  if (!event.target.closest('[data-shell-menu],[data-shell-close]')) return;
  const shell = document.querySelector('.app-shell');
  const opened = shell.classList.toggle('menu-open');
  const button = document.querySelector('[data-shell-menu]');
  button.setAttribute('aria-expanded', String(opened));
  button.setAttribute('aria-label', opened ? 'Close navigation' : 'Open navigation');
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.querySelector('.app-shell.menu-open')) {
    document.querySelector('[data-shell-menu]').click();
    document.querySelector('[data-shell-menu]').focus();
  }
});
