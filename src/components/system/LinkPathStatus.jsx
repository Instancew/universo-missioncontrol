import { useEffect, useState } from 'react';

export default function LinkPathStatus() {
  const [paths, setPaths] = useState(null);
  const [video, setVideo] = useState(null);
  const [now, setNow] = useState(0);
  useEffect(() => {
    let cancelled = false, timer;
    const poll = async () => {
      if (!cancelled) setNow(Date.now());
      try {
        const response = await fetch('/api/link-paths', { signal: AbortSignal.timeout(2000) });
        if (!response.ok) throw new Error('Path status unavailable');
        const data = await response.json();
        if (!cancelled) setPaths(data);
      } catch { if (!cancelled) setPaths(null); }
      if (!cancelled) timer = setTimeout(poll, 1000);
    };
    const receive = event => setVideo({ ...event.detail, receivedAt: Date.now() });
    window.addEventListener('irc:video-status', receive);
    poll();
    return () => { cancelled = true; clearTimeout(timer); window.removeEventListener('irc:video-status', receive); };
  }, []);
  // A dry-run selection is simulated; its health does not explain the live video route.
  const healthy = paths && !paths.dry_run && !paths.stale && paths.bands?.[paths.selected_band]?.usable === true;
  return <div className="border border-space-800 rounded p-2 text-xs font-mono text-slate-300">
    <p>{!paths || paths.stale ? 'Path monitoring unavailable/stale' : `${paths.dry_run ? 'DRY RUN — simulated selection' : 'Selected route'}: ${paths.selected_band === '5' ? '5' : '2.4'} GHz`}</p>
    {Object.entries(paths?.bands || {}).map(([band, sample]) => <p key={band}>
      {band === '5' ? '5' : '2.4'} GHz: loss {sample.valid ? `${sample.loss}%` : 'unknown'} · RTT {sample.latency_ms ?? 'unknown'} ms · associated {sample.associated == null ? 'unknown' : String(sample.associated)} · RSSI {sample.rssi ?? 'unknown'} · PHY TX/RX {sample.tx_rate ?? '?'} / {sample.rx_rate ?? '?'}
    </p>)}
    <p>{paths?.reason}</p>
    {healthy && video && now - video.receivedAt < 3000 && !video.fresh && <p className="text-amber-300">Video not fresh while selected-path probes are healthy. Investigate camera, encoder or player; no video-triggered band change.</p>}
  </div>;
}
