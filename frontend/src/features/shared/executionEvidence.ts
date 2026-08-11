const DEMO_MARKERS = [
  'OFFLINE_DEMO_UNVERIFIED',
  'unverified_demo',
  'offline-runtime',
  'offline-demo://',
];

export const containsUnverifiedDemo = (...values: unknown[]): boolean =>
  values.some((value) => {
    if (value === undefined || value === null) return false;
    const text = typeof value === 'string' ? value : JSON.stringify(value);
    return DEMO_MARKERS.some((marker) => text.includes(marker));
  });
