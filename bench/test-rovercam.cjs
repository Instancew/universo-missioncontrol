// Run with Node and an installed playwright-core. Chrome supplies the real webcam and H.264 codec.
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH || 'playwright-core');
const { join } = require('node:path');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { setTimeout: delay } = require('node:timers/promises');

const media = 'http://localhost:8889';
const dashboard = 'http://localhost:5173/';
const cameraName = process.env.ROVER_CAMERA_NAME || 'USB Camera';
const keepLive = process.argv.includes('--live');
const lowRate = process.argv.includes('--low-rate');
const checkRecovery = process.argv.includes('--check-recovery');
const skipLayout = process.argv.includes('--skip-layout');

async function verifyVideo(frame, label) {
  await frame.waitForFunction(() => {
    const video = document.querySelector('video');
    return video?.videoWidth > 0 && video.getVideoPlaybackQuality().totalVideoFrames > 2;
  }, null, { timeout: 30000 });
  const snapshot = () => frame.evaluate(async () => {
    const video = document.querySelector('video');
    for (const pc of window.testPeers) {
      if (pc.connectionState !== 'connected') continue;
      const reports = await pc.getStats();
      for (const report of reports.values()) {
        if (report.type === 'inbound-rtp' && report.kind === 'video') {
          return {
            codec: reports.get(report.codecId)?.mimeType, decoded: report.framesDecoded,
            presented: video.getVideoPlaybackQuality().totalVideoFrames,
            width: video.videoWidth, height: video.videoHeight,
          };
        }
      }
    }
    throw new Error('No connected inbound video stream');
  });
  const first = await snapshot();
  await delay(2000);
  const last = await snapshot();
  assert.equal(last.codec?.toLowerCase(), 'video/h264');
  assert.ok(last.decoded > first.decoded && last.presented > first.presented, 'Video stalled');
  console.log(label, JSON.stringify({ from: first, to: last }));
}

async function main() {
  const browser = await chromium.launch({
    executablePath: join(process.env.ProgramFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    headless: !keepLive,
    chromiumSandbox: true,
  });
  try {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    await context.grantPermissions(['camera'], { origin: media });
    // Observe the browser's negotiated codec and decoded-frame counter on the real player.
    await context.addInitScript(() => {
      window.testPeers = [];
      const Peer = window.RTCPeerConnection;
      window.RTCPeerConnection = class extends Peer {
        constructor(...args) {
          super(...args);
          window.testPeers.push(this);
        }
      };
    });
    const pub = await context.newPage();
    await pub.goto(media + '/rovercam/publish');
    await pub.locator('#publish-button').waitFor({ state: 'visible' });
    const devices = await pub.locator('#video-device option').evaluateAll(nodes =>
      nodes.map(o => ({ label: o.textContent.trim(), value: o.value })));
    const matches = devices.filter(d => d.label === cameraName || d.label.startsWith(cameraName + ' ('));
    assert.equal(matches.length, 1, 'Choose one ROVER_CAMERA_NAME from ' + devices.map(d => d.label).join(', '));
    await pub.locator('#video-device').selectOption(matches[0].value);
    await pub.locator('#audio-device').selectOption('none');
    await pub.locator('#video-codec').selectOption('h264/90000');
    await pub.locator('#video-width').fill(lowRate ? '640' : '1280');
    await pub.locator('#video-height').fill(lowRate ? '360' : '720');
    await pub.locator('#video-framerate').fill(lowRate ? '15' : '30');
    await pub.locator('#video-bitrate').fill(lowRate ? '700' : '2500');
    await pub.locator('#publish-button').click();
    console.log('Publishing', matches[0].label);
    try {
      await pub.waitForFunction(() => window.testPeers.some(pc => pc.connectionState === 'connected'), null, { timeout: 30000 });
    } catch (error) {
      console.error(await pub.evaluate(() => ({
        message: document.querySelector('#message')?.textContent,
        tracks: document.querySelector('video')?.srcObject?.getTracks().map(t => [t.label, t.readyState]),
        peers: window.testPeers.map(pc => [pc.connectionState, pc.iceConnectionState]),
      })));
      throw error;
    }
    const capture = await pub.locator('video').evaluate(v => ({
      camera: v.srcObject.getVideoTracks()[0].label, audioTracks: v.srcObject.getAudioTracks().length,
    }));
    assert.equal(capture.camera, matches[0].label);
    assert.equal(capture.audioTracks, 0);
    console.log('Publisher connected', capture);

    const reader = await context.newPage();
    const probeQuery = checkRecovery ? 'probe=' + randomUUID() : '';
    await reader.goto(media + '/rovercam/' + (probeQuery ? '?' + probeQuery : ''));
    await verifyVideo(reader.mainFrame(), 'Standalone reader');
    if (checkRecovery) {
      const api = 'http://127.0.0.1:9997/v3/webrtc/sessions';
      const response = await fetch(api + '/list');
      assert.ok(response.ok, 'Local MediaMTX session API is unavailable');
      const { items } = await response.json();
      const readers = items.filter(item => item.path === 'rovercam' && item.state === 'read'
        && item.query === probeQuery && /^(127\.0\.0\.1:|\[::1\]:)/.test(item.remoteAddr));
      assert.equal(readers.length, 1, 'Expected one local test reader');
      await reader.evaluate(() => {
        window.testPriorPeers = new Set(window.testPeers);
      });
      const start = performance.now();
      const kicked = await fetch(api + '/kick/' + readers[0].id, { method: 'POST' });
      assert.ok(kicked.ok, 'Could not end the test reader session');
      await reader.waitForFunction(() => window.testPeers.some(pc =>
        !window.testPriorPeers.has(pc) && pc.connectionState === 'connected'), null, { timeout: 35000 });
      await reader.waitForFunction(async () => {
        const peer = window.testPeers.find(pc => !window.testPriorPeers.has(pc) && pc.connectionState === 'connected');
        if (!peer) return false;
        return [...(await peer.getStats()).values()].some(report =>
          report.type === 'inbound-rtp' && report.kind === 'video' && report.framesDecoded > 0);
      }, null, { timeout: 15000 });
      console.log('Local forced disconnect to fresh frame', Math.round(performance.now() - start), 'ms');
    }
    await reader.close();

    const cockpit = await context.newPage();
    await cockpit.goto(dashboard, { waitUntil: 'domcontentloaded' });
    const player = cockpit.locator('[data-panel="primary"] iframe[title="Front Camera WebRTC player"]');
    const playerFrame = async () => {
      await player.waitFor({ state: 'visible' });
      return (await player.elementHandle()).contentFrame();
    };
    await cockpit.bringToFront();
    await player.scrollIntoViewIfNeeded();
    try {
      await verifyVideo(await playerFrame(), 'Dashboard primary camera');
    } catch (error) {
      if (!keepLive || !skipLayout) throw error;
      console.error('Dashboard playback check did not finish. Keeping the publisher live.', error.message);
    }
    if (!skipLayout) {
      const panels = () => cockpit.locator('[data-panel]').evaluateAll(nodes => nodes.map(n => n.dataset.panel));
      const before = await panels();
      assert.ok(before.includes('radio') && before.includes('imu'));
      await cockpit.getByRole('button', { name: 'Edit layout' }).click();
      const primaryHandle = cockpit.getByRole('button', { name: 'Move Primary camera' });
      const secondaryHandle = cockpit.getByRole('button', { name: 'Move Secondary camera' });
      await primaryHandle.evaluate(el => el.scrollIntoView({ block: 'start' }));
      await primaryHandle.dragTo(secondaryHandle);
      await cockpit.waitForFunction(index =>
        document.querySelectorAll('[data-panel]')[index]?.dataset.panel === 'primary',
        before.indexOf('secondary'), { timeout: 4000 });
      const after = await panels();
      assert.equal(after.indexOf('primary'), before.indexOf('secondary'));
      assert.equal(after.indexOf('secondary'), before.indexOf('primary'));
      await verifyVideo(await playerFrame(), 'Dashboard after dragging');
      await primaryHandle.click();
      await secondaryHandle.click();
      assert.deepEqual(await panels(), before);
      await cockpit.getByRole('button', { name: 'Done' }).click();
      console.log('PASS. Original panel order restored.');
    }
    if (keepLive) {
      await cockpit.bringToFront();
      await player.scrollIntoViewIfNeeded();
      console.log('Local camera is live. Close the dashboard window/tab to end this session.');
      await cockpit.waitForEvent('close', { timeout: 0 });
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
