import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Freshness, RetryBudget, startRoverVideo } from '../src/services/roverVideo.js';

test('connected player without arriving frames expires', () => {
  const f = new Freshness(0);
  assert.equal(f.fresh(1000), false);
  assert.equal(f.expired(7999), false);
  assert.equal(f.expired(8000), true);
});
test('frozen last image is stale; a new frame restores freshness', () => {
  const f = new Freshness(0);
  f.frame(100);
  assert.equal(f.fresh(2099), true);
  assert.equal(f.expired(2100), true);
  f.frame(2500);
  assert.equal(f.fresh(2500), true);
});
test('retries are finite and can reset for a later outage', () => {
  const r = new RetryBudget();
  assert.deepEqual(Array.from({ length: 6 }, () => r.next()), [250,500,1000,2000,3000,5000]);
  assert.equal(r.next(), null);
  r.reset();
  assert.equal(r.next(), 250);
});

function mockPlayer(t) {
  let now = 0, frameId = 0;
  const frames = new Map(), peers = [], calls = [], updates = [], logs = [];
  class Peer extends EventTarget {
    constructor() { super(); this.iceGatheringState = 'complete'; peers.push(this); }
    addTransceiver() {}
    async createOffer() { return { type: 'offer', sdp: 'mock-offer' }; }
    async setLocalDescription(offer) { this.localDescription = offer; }
    async setRemoteDescription() { this.ontrack({ streams: [{}] }); }
    close() { this.closed = true; }
    async getStats() { return new Map([['video', { type: 'inbound-rtp', kind: 'video', framesDropped: 2, packetsLost: 3 }]]); }
  }
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  t.mock.method(performance, 'now', () => now);
  const previous = globalThis.RTCPeerConnection;
  globalThis.RTCPeerConnection = Peer;
  t.after(() => { globalThis.RTCPeerConnection = previous; });
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, ...options });
    return { ok: true, headers: new Headers({ Location: '/rovercam/whep/session' }), text: async () => 'mock-answer' };
  });
  const video = { play: async () => {}, requestVideoFrameCallback: cb => { frames.set(++frameId, cb); return frameId; }, cancelVideoFrameCallback: id => frames.delete(id) };
  const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
  const tick = async ms => { now += ms; t.mock.timers.tick(ms); await flush(); };
  const frame = () => { const entries = [...frames]; frames.clear(); for (const [,cb] of entries) cb(); };
  const stop = startRoverVideo(video, 'http://rover.test/rovercam/whep', state => updates.push({ ...state }), msg => logs.push(msg));
  t.after(stop);
  return { tick, flush, frame, stop, peers, calls, updates, logs, frames, video };
}

test('real receiver lifecycle flags stalled frames, recovers and cleans WHEP sessions', async t => {
  const m = mockPlayer(t);
  await m.flush();
  m.frame(); await m.tick(250);
  assert.equal(m.updates.at(-1).fresh, true);
  assert.equal(m.updates.at(-1).drops, 2);
  await m.tick(2000);
  assert.equal(m.updates.at(-1).fresh, false);
  assert.equal(m.peers[0].closed, true);
  assert.ok(m.calls.some(c => c.method === 'DELETE'));
  await m.tick(250);
  m.frame(); await m.tick(250);
  assert.equal(m.peers.length, 2);
  assert.equal(m.updates.at(-1).fresh, true);
  assert.equal(m.logs.filter(log => log.includes('fresh video resumed')).length, 2);
  m.stop(); await m.tick(10000);
  assert.ok(m.peers.every(peer => peer.closed));
  assert.equal(m.frames.size, 0);
  assert.equal(m.video.srcObject, null);
});

test('receiver stops automatic retries when every session lacks frames', async t => {
  const m = mockPlayer(t);
  await m.flush();
  for (const delay of [250,500,1000,2000,3000,5000]) {
    await m.tick(8000);
    await m.tick(delay);
  }
  await m.tick(8000);
  assert.equal(m.peers.length, 7);
  assert.equal(m.updates.at(-1).state, 'retry limit reached');
  await m.tick(60000);
  assert.equal(m.peers.length, 7);
});
