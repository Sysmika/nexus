// Nexus by Orion · marca sobre Home Assistant (capa 1 + PWA)
// Se carga con `frontend: extra_module_url` (/local/nexus/nexus-branding.js) y cambia solo lo que ve el usuario:
//   · título del sidebar y de la pestaña del navegador
//   · íconos (favicon, ícono de iOS) y manifest de la PWA: la app se instala como "Nexus"
//   · para usuarios NO administradores, oculta del sidebar todo lo que no sea un dashboard
// No modifica Home Assistant ni su licencia: es una capa visual.
(() => {
  if (window.__nexusBranding) return;
  window.__nexusBranding = true;

  const BASE = '/local/nexus/';
  const CFG = {
    nombre: 'Nexus',
    original: 'Home Assistant',
    favicon: BASE + 'icon-192.png',
    appleIcon: BASE + 'apple-touch-icon.png',
    manifest: BASE + 'manifest.webmanifest',
    // Paneles que ve un usuario no administrador además de los dashboards (url_path)
    panelesExtra: [],
    // true: oculta el sidebar "de sistema" a los no administradores (es solo visual, no es seguridad)
    simplificarParaClientes: true,
  };

  const ha = () => document.querySelector('home-assistant');
  const sidebar = () => {
    const main = ha()?.shadowRoot?.querySelector('home-assistant-main');
    return main?.shadowRoot?.querySelector('ha-sidebar') || null;
  };

  // --- título de la pestaña ---
  const arreglarTitulo = () => {
    if (document.title.includes(CFG.original)) {
      document.title = document.title.split(CFG.original).join(CFG.nombre);
    }
  };
  const observarTitulo = () => {
    const t = document.querySelector('title');
    if (!t) return;
    new MutationObserver(arreglarTitulo).observe(t, { childList: true, characterData: true, subtree: true });
    arreglarTitulo();
  };

  // --- íconos, manifest y nombre de la app instalada ---
  const asegurarLink = (rel, href) => {
    let l = document.querySelector(`link[rel="${rel}"]`);
    if (!l) {
      l = document.createElement('link');
      l.rel = rel;
      document.head.appendChild(l);
    }
    if (l.getAttribute('href') !== href) l.setAttribute('href', href);
    return l;
  };
  const arreglarIconos = () => {
    document.querySelectorAll('link[rel~="icon"]').forEach((l) => {
      if (l.getAttribute('href') !== CFG.favicon) {
        l.setAttribute('href', CFG.favicon);
        l.removeAttribute('type');
        l.removeAttribute('sizes');
      }
    });
    asegurarLink('apple-touch-icon', CFG.appleIcon);
    // Manifest propio: Chrome/Edge lo toman al ofrecer "Instalar"
    const m = asegurarLink('manifest', CFG.manifest);
    m.removeAttribute('crossorigin');
    const meta = (name, content) => {
      let e = document.querySelector(`meta[name="${name}"]`);
      if (!e) {
        e = document.createElement('meta');
        e.name = name;
        document.head.appendChild(e);
      }
      if (e.content !== content) e.content = content;
    };
    meta('apple-mobile-web-app-title', CFG.nombre);
    meta('application-name', CFG.nombre);
    meta('theme-color', '#1f4b7d');
  };

  // --- sidebar ---
  const arreglarSidebar = () => {
    const root = sidebar()?.shadowRoot;
    if (!root) return;

    // título "Home Assistant" -> "Nexus"
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      if (n.nodeValue.trim() === CFG.original) n.nodeValue = CFG.nombre;
    }

    // usuarios no administradores: solo dashboards
    const hass = ha()?.hass;
    if (!CFG.simplificarParaClientes || !hass?.user || hass.user.is_admin) return;
    root.querySelectorAll('a[href]').forEach((a) => {
      const panel = a.dataset.panel || new URL(a.href, location.origin).pathname.split('/')[1];
      const info = hass.panels?.[panel];
      const visible = (info && info.component_name === 'lovelace') || CFG.panelesExtra.includes(panel);
      const oculto = a.style.display === 'none';
      if (!visible && !oculto) a.style.display = 'none';
      if (visible && oculto) a.style.display = '';
    });
  };

  // --- marca de agua (solo con el tema "Nexus": su variable nexus-marca-agua vale 1) ---
  const arreglarMarcaAgua = () => {
    const activa = getComputedStyle(document.documentElement).getPropertyValue('--nexus-marca-agua').trim().replace(/"/g, '') === '1';
    let e = document.getElementById('nexus-marca-agua');
    if (!activa) {
      if (e) e.remove();
      return;
    }
    if (e) return;
    e = document.createElement('div');
    e.id = 'nexus-marca-agua';
    e.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483000;opacity:.10;'
      + 'background:url(' + BASE + 'marca-agua.png) center / min(62vw,900px) no-repeat';
    document.body.appendChild(e);
  };

  const ciclo = () => {
    try {
      arreglarIconos();
      arreglarSidebar();
      arreglarMarcaAgua();
    } catch (e) {
      console.warn('[nexus-branding]', e);
    }
  };

  observarTitulo();
  ciclo();
  setInterval(ciclo, 1000);
})();
