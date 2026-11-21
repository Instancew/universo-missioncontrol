import { useEffect, useRef, useState } from 'react';
import { startRoverVideo } from '../../services/roverVideo';
import { useRover } from '../../context/RoverContext';

export default function RoverWebRTC({ url }) {
  const { addLog } = useRover();
  const video = useRef(null);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState({ state: 'connecting', fresh: false });
  useEffect(() => {
    if (!url) return;
    return startRoverVideo(video.current, url, next => {
      setStatus(next);
      window.dispatchEvent(new CustomEvent('irc:video-status', { detail: next }));
    }, message => { console.info(message); addLog(message, 'INFO', 'CAM'); });
  }, [url, attempt, addLog]);
  return <div className="absolute inset-0 bg-black">
    <video ref={video} autoPlay muted playsInline className="h-full w-full object-contain" aria-label="Front Camera live video" />
    <div role="status" aria-live="polite" className={`absolute left-2 right-2 bottom-10 z-30 p-2 text-xs font-mono bg-black/85 ${status.fresh ? 'text-emerald-400' : 'text-amber-300'}`}>
      {!url ? 'Configure VITE_ROVER_WHEP_URL' : status.fresh ? 'LIVE — fresh frames' : `VIDEO NOT FRESH — ${status.state}`}
      <span className="block">Frame age: {status.ageMs == null ? 'unknown' : `${Math.round(status.ageMs)} ms`} · Dropped frames: {status.drops ?? 'unavailable'} · RTP packets lost: {status.lost ?? 'unavailable'}</span>
      {!status.fresh && <button type="button" className="underline mt-1" onClick={() => setAttempt(value => value + 1)}>Retry video</button>}
    </div>
  </div>;
}
