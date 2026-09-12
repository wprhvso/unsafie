const KEY = 'answer-zoom';
const VARIABLE = '--live-zoom';
const MIN = 0.2;
const MAX = 4;
const DEFAULT = 1;
const SAVE_MS = 250;

function isAndroid() {
  if (typeof navigator === 'undefined') return false;
  return /android/i.test(navigator.userAgent);
}

function restore(key) {
  try {
    const value = parseFloat(localStorage.getItem(key));
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

export function zoomer({ key = KEY, variable = VARIABLE, onchange } = {}) {
  if (!isAndroid()) {
    if (typeof document !== 'undefined') {
      document.documentElement.style.removeProperty(variable);
    }
    return {
      get value() { return DEFAULT; },
      in: () => {},
      out: () => {},
      reset: () => {},
      stop: () => {}
    };
  }

  let zoom = restore(key);
  let anchor = zoom;
  let start = 0;
  let timer = 0;

  const apply = (value) => {
    zoom = Math.min(MAX, Math.max(MIN, value));
    document.documentElement.style.setProperty(variable, zoom.toFixed(4));
    onchange?.(zoom);
  };

  const write = () => {
    timer = 0;
    try {
      localStorage.setItem(key, String(zoom));
    } catch {
      void 0;
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

  apply(zoom);
  document.addEventListener('touchstart', onStart, { passive: true });
  document.addEventListener('touchmove', onMove, { passive: false });
  document.addEventListener('touchend', onEnd);
  document.addEventListener('touchcancel', onEnd);

  return {
    get value() {
      return zoom;
    },
    in: () => {},
    out: () => {},
    reset: () => {
      apply(DEFAULT);
      save();
    },
    stop: () => {
      document.removeEventListener('touchstart', onStart);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onEnd);
      document.removeEventListener('touchcancel', onEnd);
      if (timer) {
        clearTimeout(timer);
        write();
      }
      document.documentElement.style.removeProperty(variable);
    }
  };
}

export function zoomable(options) {
  const control = zoomer(options);
  return () => control.stop();
}
