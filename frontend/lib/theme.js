'use client';

import { useSyncExternalStore } from 'react';

// The resolved theme lives on <html data-theme="light|dark">. It is set
// before first paint by the inline script in app/layout.js (saved choice,
// else the OS setting), so there is no flash of the wrong theme.
// Same localStorage key ('theme') as the old app.

function subscribe(callback) {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  return () => observer.disconnect();
}

const getSnapshot = () => document.documentElement.dataset.theme || 'light';

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, () => 'light');
  const setTheme = (next) => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('theme', next);
    } catch {
      // ignore
    }
  };
  return { theme, setTheme, toggle: () => setTheme(theme === 'dark' ? 'light' : 'dark') };
}

// Reads the current CSS custom properties so canvas charts match the theme.
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}