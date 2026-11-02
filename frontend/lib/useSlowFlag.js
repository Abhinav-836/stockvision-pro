'use client';

import { useEffect, useState } from 'react';

// True once `active` has stayed true for `ms` milliseconds. Used to explain
// slow first loads (Render cold start) instead of an endless spinner.
export default function useSlowFlag(active, ms = 5000) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) {
      setSlow(false);
      return undefined;
    }
    const id = setTimeout(() => setSlow(true), ms);
    return () => clearTimeout(id);
  }, [active, ms]);
  return slow;
}