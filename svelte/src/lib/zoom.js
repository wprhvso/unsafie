/**
 * Zoom of the share page: a pinch with two fingers, ctrl+wheel on a desktop.
 *
 * The scale lives in the --answer-zoom custom property and survives reloads in
 * localStorage; the page is scaled with the CSS zoom property, so paddings and
 * the measure of the text scale along with it.
 */

const KEY = 'answer-zoom';
const MIN = 0.2;
const MAX = 5;
const DEFAULT = 1;
const SAVE_MS = 250;

function restore() {
  try {
    const value = parseFloat(localStorage.getItem(KEY));
    return value >= MIN && value <= MAX ? value : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

function spread(touches) {
  return Math.hypot(
    touches[0].clientX - touches[1].clientX,
    touches[0].clientY - touches[1].clientY
  );
}

/** Attaches the gestures to the document; returns a teardown function. */
export function zoomable() {
  let zoom = restore();
  let anchor = zoom;
  let start = 0;
  let timer = 0;

  const apply = (value) => {
    zoom = Math.min(MAX, Math.max(MIN, value));
    document.documentElement.style.setProperty('--answer-zoom', zoom.toFixed(4));
  };

  const write = () => {
    timer = 0;
    try {
      localStorage.setItem(KEY, String(zoom));
    } catch {
      /* storage disabled — the zoom simply does not survive the reload */
    }
  };

  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(write, SAVE_MS);
  };

  const onStart = (event) => {
    if (event.touches.length === 2) {
      start = spread(event.touches);
      anchor = zoom;
    }
  };

  const onMove = (event) => {
    if (event.touches.length === 2 && start > 0) {
      event.preventDefault();
      apply((anchor * spread(event.touches)) / start);
    }
  };

  const onEnd = (event) => {
    if (event.touches.length < 2 && start > 0) {
      start = 0;
      save();
    }
  };

  const onWheel = (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    apply(zoom * Math.exp(-event.deltaY * 0.002));
    save();
  };

  apply(zoom);
  document.addEventListener('touchstart', onStart, { passive: true });
  document.addEventListener('touchmove', onMove, { passive: false });
  document.addEventListener('touchend', onEnd);
  document.addEventListener('touchcancel', onEnd);
  document.addEventListener('wheel', onWheel, { passive: false });

  return () => {
    document.removeEventListener('touchstart', onStart);
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onEnd);
    document.removeEventListener('touchcancel', onEnd);
    document.removeEventListener('wheel', onWheel);
    if (timer) {
      clearTimeout(timer);
      write();
    }
    document.documentElement.style.removeProperty('--answer-zoom');
  };
}
