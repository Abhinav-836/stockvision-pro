'use client';

import { useSyncExternalStore } from 'react';

// Same localStorage key as the old Vite app, so existing visitors keep
// their watchlist after the redesign.
const KEY = 'watchlist';
const EMPTY = [];
const listeners = new Set();
let snapshot = null;

function read() {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(parsed) ? parsed.filter((s) => typeof s === 'string') : [];
  } catch {
    return [];
  }
}

function getSnapshot() {
  if (snapshot === null) snapshot = read();
  return snapshot;
}

function write(list) {
  snapshot = list;
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    // storage blocked (private mode); keep the in-memory list
  }
  listeners.forEach((l) => l());
}

function subscribe(listener) {
  listeners.add(listener);
  const onStorage = (e) => {
    if (e.key === KEY) {
      snapshot = read();
      listener();
    }
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

export function useWatchlist() {
  const list = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
  const has = (symbol) => list.includes(String(symbol).toUpperCase());
  const add = (symbol) => {
    const s = String(symbol).toUpperCase();
    if (!getSnapshot().includes(s)) write([...getSnapshot(), s]);
  };
  const remove = (symbol) => {
    const s = String(symbol).toUpperCase();
    write(getSnapshot().filter((x) => x !== s));
  };
  const toggle = (symbol) => (has(symbol) ? remove(symbol) : add(symbol));
  return { list, has, add, remove, toggle };
}