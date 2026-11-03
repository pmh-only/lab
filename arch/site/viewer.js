/* global OpenSeadragon */
'use strict';

async function start() {
  const status = document.getElementById('status');
  const response = await fetch('/manifest.json', { cache: 'no-cache' });
  if (!response.ok) throw new Error(`manifest HTTP ${response.status}`);
  const manifest = await response.json();
  document.getElementById('dimensions').textContent =
    `${manifest.width.toLocaleString()} × ${manifest.height.toLocaleString()} · 무손실 Deep Zoom`;
  for (const [id, key] of [['download-png', 'image'], ['download-drawio', 'drawing']]) {
    const link = document.getElementById(id);
    link.href = manifest[key];
    link.hidden = false;
  }
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const viewer = window.viewer = OpenSeadragon({
    id: 'viewer',
    prefixUrl: '/vendor/openseadragon/images/',
    tileSources: manifest.tileSource,
    showNavigationControl: false,
    showNavigator: true,
    navigatorPosition: 'BOTTOM_RIGHT',
    navigatorAutoFade: true,
    navigatorWidth: 100,
    navigatorHeight: 112,
    visibilityRatio: 0.5,
    constrainDuringPan: true,
    maxZoomPixelRatio: 2,
    minZoomImageRatio: 0.8,
    animationTime: reducedMotion ? 0 : 0.5,
    blendTime: reducedMotion ? 0 : 0.15,
    gestureSettingsTouch: { pinchToZoom: true, flickEnabled: true },
  });
  const regions = {
    entry: [180, 30, 3300, 1250],
    nodes: [50, 570, 1040, 2600],
    apps: [1090, 1260, 1350, 1300],
    identity: [1800, 750, 640, 420],
    observability: [2570, 750, 1080, 670],
    routing: [2570, 1580, 1080, 830],
    storage: [1080, 2560, 2580, 960],
    external: [60, 3600, 3670, 570],
  };
  viewer.addHandler('open', () => { status.hidden = true; });
  viewer.addHandler('open-failed', () => {
    status.textContent = '도면을 불러오지 못했습니다. 페이지를 새로고침해 주세요.';
    status.hidden = false;
  });
  viewer.addHandler('tile-load-failed', () => {
    status.textContent = '일부 타일을 불러오지 못했습니다. 연결을 확인하고 새로고침해 주세요.';
    status.hidden = false;
  });
  viewer.addHandler('animation', () => {
    const image = viewer.world.getItemAt(0);
    if (!image) return;
    const percent = image.viewportToImageZoom(viewer.viewport.getZoom(true)) * 100;
    document.getElementById('zoom').textContent = `${Math.round(percent)}% · 원본 픽셀 기준`;
  });
  viewer.addHandler('open', () => viewer.raiseEvent('animation'));
  document.getElementById('zoom-in').onclick = () => {
    if (viewer.isOpen()) viewer.viewport.zoomBy(1.5).applyConstraints();
  };
  document.getElementById('zoom-out').onclick = () => {
    if (viewer.isOpen()) viewer.viewport.zoomBy(1 / 1.5).applyConstraints();
  };
  const home = () => {
    if (viewer.isOpen()) viewer.viewport.goHome();
    document.getElementById('region').value = 'all';
  };
  document.getElementById('home').onclick = home;
  document.getElementById('region').onchange = (event) => {
    if (!viewer.isOpen()) return;
    const coordinates = regions[event.target.value];
    if (!coordinates) return home();
    const scale = manifest.width / 3840;
    const [x, y, w, h] = coordinates.map((value) => value * scale);
    const item = viewer.world.getItemAt(0);
    viewer.viewport.fitBounds(item.imageToViewportRectangle(x, y, w, h), true);
  };
  const fullscreen = document.getElementById('fullscreen');
  fullscreen.hidden = !document.fullscreenEnabled;
  fullscreen.onclick = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch {
      status.textContent = '이 브라우저에서는 전체 화면을 사용할 수 없습니다.';
      status.hidden = false;
    }
  };
  document.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey ||
        ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'A'].includes(event.target.tagName)) return;
    if (event.key.toLowerCase() === 'h') { event.preventDefault(); home(); }
    if (event.key.toLowerCase() === 'f' && !fullscreen.hidden) {
      event.preventDefault(); fullscreen.click();
    }
  });
}

start().catch((error) => {
  console.error(error);
  const status = document.getElementById('status');
  status.textContent = '뷰어를 불러오지 못했습니다. 페이지를 새로고침해 주세요.';
  status.hidden = false;
});
