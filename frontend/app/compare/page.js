import { Suspense } from 'react';
import CompareView from '@/components/CompareView';

export const metadata = { title: 'Compare stocks' };

export default function ComparePage() {
  // useSearchParams needs a Suspense boundary for static rendering
  return (
    <Suspense fallback={null}>
      <CompareView />
    </Suspense>
  );
}