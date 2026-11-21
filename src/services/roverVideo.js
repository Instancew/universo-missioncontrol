// WHEP receiver: freshness means decoded/presented frames, never ICE state alone.
export class Freshness {
  constructor(now, staleMs = 2000) { this.started = now; this.last = null; this.staleMs = staleMs; }
  frame(now) { this.last = now; }
  fresh(now) { return this.last !== null && now - this.last < this.staleMs; }
  expired(now) { return now - (this.last ?? this.started) >= (this.last === null ? 8000 : this.staleMs); }
}

export class RetryBudget {
  constructor() { this.used = 0; }
  next() { return [250, 500, 1000, 2000, 3000, 5000][this.used++] ?? null; }
  reset() { this.used = 0; }
}

export function startRoverVideo(video, url, report, log = console.info) {
  let stopped = false, current = null, retryTimer, tickBusy = false, lastFrameAt = null;
  const retries = new RetryBudget();
  let status = { state: 'connecting', fresh: false, drops: null, lost: null, ageMs: null };
  const emit = patch => { status = { ...status, ...patch }; if (!stopped) report(status); };
  const removeSession = session => {
    if (session) fetch(session, { method: 'DELETE', signal: AbortSignal.timeout(2000) }).catch(() => {});
  };
  const close = () => {
    const old = current;
    current = null;
    if (!old) return;
    old.abort.abort();
    clearTimeout(old.deadline);
    old.pc.close();
    if (old.frameId !== undefined) video.cancelVideoFrameCallback?.(old.frameId);
    removeSession(old.session);
    // Preserve the last image, labelled stale, until replacement frames arrive.
  };
  const fail = reason => {
    if (stopped || !current) return;
    close();
    const delay = retries.next();
    emit({ state: delay === null ? 'retry limit reached' : 'reconnecting', fresh: false, reason });
    log(`[rovercam] ${reason}; ${delay === null ? 'manual retry needed' : `retry in ${delay} ms`}`);
    if (delay !== null) retryTimer = setTimeout(connect, delay);
  };
  async function connect() {
    if (stopped) return;
    const pc = new RTCPeerConnection({ iceServers: [] });
    const attempt = { pc, abort: new AbortController(), freshness: new Freshness(performance.now()), lastDecoded: 0, stableSince: null };
    current = attempt;
    const valid = () => !stopped && current === attempt;
    emit({ state: 'connecting', fresh: false, ageMs: null, drops: null, lost: null, reason: '' });
    attempt.deadline = setTimeout(() => { if (valid()) fail('connection deadline'); }, 8000);
    pc.ontrack = event => {
      if (!valid()) return;
      video.srcObject = event.streams[0] || new MediaStream([event.track]);
      video.play().catch(() => { if (valid()) fail('browser refused playback'); });
    };
    pc.onconnectionstatechange = () => {
      if (valid() && pc.connectionState === 'failed') fail('WebRTC transport failed');
    };
    const frame = () => {
      if (!valid()) return;
      const now = performance.now();
      if (!attempt.freshness.fresh(now)) log('[rovercam] fresh video resumed');
      attempt.freshness.frame(now);
      lastFrameAt = now;
      attempt.stableSince ??= now;
      clearTimeout(attempt.deadline);
    };
    if (video.requestVideoFrameCallback) {
      const presented = () => { frame(); if (valid()) attempt.frameId = video.requestVideoFrameCallback(presented); };
      attempt.frameId = video.requestVideoFrameCallback(presented);
    }
    attempt.frame = frame;
    try {
      pc.addTransceiver('video', { direction: 'recvonly' });
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise((resolve, reject) => {
        const cleanup = () => { clearTimeout(timer); pc.removeEventListener('icegatheringstatechange', change); attempt.abort.signal.removeEventListener('abort', aborted); };
        const change = () => { if (pc.iceGatheringState === 'complete') { cleanup(); resolve(); } };
        const aborted = () => { cleanup(); reject(new Error('cancelled')); };
        const timer = setTimeout(() => { cleanup(); reject(new Error('ICE gathering timeout')); }, 3000);
        pc.addEventListener('icegatheringstatechange', change);
        attempt.abort.signal.addEventListener('abort', aborted, { once: true });
        change();
      });
      if (!valid()) return;
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: pc.localDescription.sdp, signal: attempt.abort.signal });
      if (!response.ok) throw new Error(`WHEP HTTP ${response.status}`);
      const location = response.headers.get('Location');
      const session = location ? new URL(location, url).href : null;
      // Never send a DELETE to an unrelated origin supplied by a server header.
      if (session && new URL(session).origin !== new URL(url).origin) throw new Error('Unexpected WHEP session origin');
      if (!valid()) { removeSession(session); return; }
      attempt.session = session;
      await pc.setRemoteDescription({ type: 'answer', sdp: await response.text() });
    } catch (error) { if (valid()) fail(error.message); }
  }
  const ticker = setInterval(async () => {
    const attempt = current;
    if (stopped) return;
    const now = performance.now();
    if (!attempt) {
      // Keep the mounted player's diagnosis current during backoff and after exhaustion.
      // Cleanup clears this ticker, allowing consumers to expire an unmounted player.
      emit({ fresh: false, ageMs: lastFrameAt === null ? null : now - lastFrameAt });
      return;
    }
    if (attempt.freshness.expired(now)) { fail('fresh frames stopped'); return; }
    emit({ fresh: attempt.freshness.fresh(now), state: attempt.freshness.fresh(now) ? 'live' : 'connecting', ageMs: lastFrameAt === null ? null : now - lastFrameAt });
    if (attempt.stableSince !== null && now - attempt.stableSince >= 10000 && attempt.freshness.fresh(now)) retries.reset();
    if (tickBusy) return;
    tickBusy = true;
    try {
      const stats = await attempt.pc.getStats();
      if (current !== attempt || stopped) return;
      stats.forEach(stat => {
        if (stat.type !== 'inbound-rtp' || (stat.kind || stat.mediaType) !== 'video') return;
        if (!video.requestVideoFrameCallback && stat.framesDecoded > attempt.lastDecoded) attempt.frame();
        attempt.lastDecoded = stat.framesDecoded ?? attempt.lastDecoded;
        emit({ drops: stat.framesDropped ?? null, lost: stat.packetsLost ?? null });
      });
    } catch { /* Missing optional statistics never imply healthy video. */ }
    finally { tickBusy = false; }
  }, 250);
  connect();
  return () => { stopped = true; clearInterval(ticker); clearTimeout(retryTimer); close(); video.srcObject = null; };
}
