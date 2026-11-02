'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { stockPath } from '@/lib/format';
import { SUGGESTIONS } from '@/lib/symbols';

export default function SymbolSearch({ autoFocus = false, size = 'md', shortcut = false }) {
  const router = useRouter();
  const listId = useId();
  const inputRef = useRef(null);
  const [value, setValue] = useState('');

  // "/" focuses the header search from anywhere on the page.
  useEffect(() => {
    if (!shortcut) return undefined;
    const onKey = (e) => {
      const tag = document.activeElement?.tagName;
      if (e.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [shortcut]);

  const submit = (e) => {
    e.preventDefault();
    const symbol = value.trim().toUpperCase();
    if (!symbol) return;
    setValue('');
    inputRef.current?.blur();
    router.push(stockPath(symbol));
  };

  return (
    <form className={`search search-${size}`} onSubmit={submit} role="search">
      <label htmlFor={`${listId}-input`} className="sr-only">
        Stock symbol
      </label>
      <input
        id={`${listId}-input`}
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase().replace(/[^A-Z0-9.&^=-]/g, '').slice(0, 20))}
        placeholder="Symbol, e.g. AAPL or RELIANCE.NS"
        list={listId}
        autoComplete="off"
        autoCapitalize="characters"
        spellCheck={false}
        autoFocus={autoFocus}
      />
      {shortcut && <kbd className="search-kbd">/</kbd>}
      <datalist id={listId}>
        {SUGGESTIONS.map(([s, name]) => (
          <option key={s} value={s}>
            {name}
          </option>
        ))}
      </datalist>
      {size === 'lg' && (
        <button type="submit" className="btn">
          Look up
        </button>
      )}
    </form>
  );
}