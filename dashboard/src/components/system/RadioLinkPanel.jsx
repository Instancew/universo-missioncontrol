import React, { useEffect, useMemo, useState } from 'react';
import { useRover } from '../../context/RoverContext';


const MAX_HISTORY = 600; // Up to 600 samples; at 5-second polling this is about 50 minutes
const CHART = {
  width: 900,
  height: 270,
  left: 68,
  right: 18,
  top: 18,
  bottom: 48,
};
const PLOT_WIDTH = CHART.width - CHART.left - CHART.right;
const PLOT_HEIGHT = CHART.height - CHART.top - CHART.bottom;

const numberOrNull = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
};

const formatRate = (value) => {
  const n = numberOrNull(value);
  if (n === null) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)} Gbps`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} Mbps`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} kbps`;
  return `${n.toFixed(0)} bps`;
};

const formatMemory = (value) => {
  const n = numberOrNull(value);
  return n === null ? '—' : `${(n / 1048576).toFixed(1)} MB`;
};

const formatDbm = (value) => {
  const n = numberOrNull(value);
  return n === null ? 'N/A' : `${n.toFixed(0)} dBm`;
};

const formatDb = (value) => {
  const n = numberOrNull(value);
  return n === null ? 'N/A' : `${n.toFixed(0)} dB`;
};

const signalTone = (value) => {
  if (value === null) return 'text-slate-500';
  if (value <= -85) return 'text-cyber-red';
  if (value <= -75) return 'text-cyber-orange';
  return 'text-cyber-cyan';
};

const signalWidth = (value) => {
  if (value === null) return 0;
  return Math.max(0, Math.min(100, ((value + 100) / 60) * 100));
};

const makeSample = (router) => {
  const wireless = router?.wireless || {};
  return {
    signal: numberOrNull(wireless.signal_dbm),
    noiseFloor: numberOrNull(wireless.noise_floor_dbm),
    snr: numberOrNull(wireless.snr_db),
    txThroughput: numberOrNull(wireless.tx_throughput_bps),
    rxThroughput: numberOrNull(wireless.rx_throughput_bps),
    txRate: numberOrNull(wireless.tx_rate_bps),
    rxRate: numberOrNull(wireless.rx_rate_bps),
    linkStatus: wireless.link_status || 'unknown',
  };
};

function RouterCard({ router, title }) {
  const system = router?.system || {};
  const wireless = router?.wireless || {};
  const signal = numberOrNull(wireless.signal_dbm);
  const noiseFloor = numberOrNull(wireless.noise_floor_dbm);
  const snr = numberOrNull(wireless.snr_db);
  const cpu = numberOrNull(system.cpu_load_percent);
  const freeMemory = numberOrNull(system.free_memory_bytes);
  const totalMemory = numberOrNull(system.total_memory_bytes);

  const memoryUsed = (
    freeMemory !== null && totalMemory !== null && totalMemory > 0
  ) ? Math.round(((totalMemory - freeMemory) / totalMemory) * 100) : null;

  const apiStatus = router?.api_status || 'unknown';
  const apiHealthy = apiStatus === 'online' || apiStatus === 'partial';
  const isConnected = wireless.link_status === 'connected';
  const linkLabel = wireless.link_status?.toUpperCase() || 'NO LINK DATA';

  return (
    <div className="hud-panel p-4 border border-space-800 bg-[#0b0f19]/70 relative overflow-hidden min-w-0">
      <div className="flex justify-between items-start gap-2 border-b border-space-800/70 pb-3 mb-4">
        <div>
          <div className="text-[10px] text-slate-500 tracking-[0.2em] font-bold">WIRELESS DEVICE</div>
          <h3 className="text-sm text-cyber-amber font-black mt-1 uppercase">{title}</h3>
          <div className="text-[9px] text-slate-500 mt-1">{router?.ip || 'IP unavailable'}</div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className={`text-[9px] font-black px-2 py-1 rounded border ${
            apiHealthy
              ? apiStatus === 'partial'
                ? 'text-amber-300 border-amber-500/40 bg-amber-500/10'
                : 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10'
              : 'text-cyber-red border-red-500/40 bg-red-500/10'
          }`}>
            {`API ${apiStatus.toUpperCase()}`}
          </span>
          <span className={`text-[9px] font-bold ${isConnected ? 'text-emerald-400' : 'text-slate-500'}`}>
            ● {linkLabel}
          </span>
        </div>
      </div>

      <div className="bg-[#060608]/75 border border-space-850 rounded-lg p-3 mb-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[9px] text-slate-500 font-bold tracking-widest">PEER SIGNAL STRENGTH</span>
          <span className="text-[8px] text-slate-600">RSSI AT THIS ROUTER</span>
        </div>
        <div className={`text-3xl font-black tabular-nums ${signalTone(signal)}`}>{formatDbm(signal)}</div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden mt-3">
          <div
            className="h-full bg-current transition-all duration-100"
            style={{
              width: `${signalWidth(signal)}%`,
              color: signal !== null && signal <= -85
                ? '#ef4444'
                : signal !== null && signal <= -75 ? '#f59e0b' : '#06b6d4',
            }}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <Metric label="TX LINK RATE" value={formatRate(wireless.tx_rate_bps)} />
        <Metric label="RX LINK RATE" value={formatRate(wireless.rx_rate_bps)} />
        <Metric label="TX THROUGHPUT" value={formatRate(wireless.tx_throughput_bps)} />
        <Metric label="RX THROUGHPUT" value={formatRate(wireless.rx_throughput_bps)} />
        <Metric label="NOISE FLOOR" value={formatDbm(noiseFloor)} />
        <Metric label="SNR" value={formatDb(snr)} />
      </div>

      <div className="border-t border-space-800/70 pt-3">
        <div className="text-[9px] text-cyber-amber/70 font-bold tracking-widest mb-2">SYSTEM DIAGNOSTICS</div>
        <div className="grid grid-cols-2 gap-y-2 gap-x-3 text-[9px]">
          <Info label="CPU LOAD" value={cpu === null ? '—' : `${cpu}%`} />
          <Info label="MEMORY FREE" value={formatMemory(freeMemory)} />
          <Info label="MEMORY USED" value={memoryUsed === null ? '—' : `${memoryUsed}%`} />
          <Info label="UPTIME" value={system.uptime || '—'} />
          <Info label="INTERFACE" value={wireless.interface || '—'} />
          <Info label="SSID" value={wireless.ssid || '—'} />
          <Info label="ROUTEROS" value={system.version || '—'} />
          <Info label="AUTHORIZED" value={
            wireless.authorized === null || wireless.authorized === undefined
              ? '—' : wireless.authorized ? 'YES' : 'NO'
          } />
        </div>
      </div>

      {router?.errors && (router.errors.system || router.errors.wireless) && (
        <div className="mt-3 text-[9px] text-cyber-red border-t border-space-800 pt-2 break-words">
          {router.errors.wireless || router.errors.system}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="bg-[#060608]/75 border border-space-850 rounded p-2 min-w-0">
      <div className="text-[8px] text-slate-500 font-bold tracking-wide">{label}</div>
      <div className="text-[11px] text-cyber-amber font-black mt-1 break-words tabular-nums">{value}</div>
    </div>
  );
}

function Info({ label, value }) {
  return (
    <div className="min-w-0 flex flex-col gap-0.5">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-300 font-bold truncate" title={String(value)}>{value}</span>
    </div>
  );
}

const METRICS = [
  { key: 'signal', label: 'SIGNAL (dBm)' },
  { key: 'noiseFloor', label: 'NOISE FLOOR (dBm)' },
  { key: 'snr', label: 'SNR (dB)' },
  { key: 'throughput', label: 'THROUGHPUT' },
  { key: 'linkRate', label: 'LINK RATE' },
];

const metricConfig = (key) => {
  if (key === 'signal') {
    return {
      unit: 'dBm', min: -100, max: -40,
      series: [{ key: 'signal', label: 'Signal received', color: '#f59e0b' }],
    };
  }
  if (key === 'noiseFloor') {
    return {
      unit: 'dBm', min: -120, max: -60,
      series: [{ key: 'noiseFloor', label: 'Noise floor', color: '#a78bfa' }],
    };
  }
  if (key === 'snr') {
    return {
      unit: 'dB', min: 0, max: 60,
      series: [{ key: 'snr', label: 'SNR', color: '#34d399' }],
    };
  }
  if (key === 'throughput') {
    return {
      unit: 'Mbps', min: 0, max: null,
      series: [
        { key: 'txThroughput', label: 'TX throughput', color: '#f59e0b' },
        { key: 'rxThroughput', label: 'RX throughput', color: '#06b6d4' },
      ],
    };
  }
  return {
    unit: 'Mbps', min: 0, max: null,
    series: [
      { key: 'txRate', label: 'TX link rate', color: '#f59e0b' },
      { key: 'rxRate', label: 'RX link rate', color: '#06b6d4' },
    ],
  };
};

const chartValue = (metricKey, value) => {
  if (value === null || value === undefined) return null;
  return (metricKey === 'throughput' || metricKey === 'linkRate') ? value / 1_000_000 : value;
};

const formatChartValue = (metricKey, value) => {
  const n = chartValue(metricKey, value);
  if (n === null || !Number.isFinite(n)) return 'N/A';
  if (metricKey === 'signal' || metricKey === 'noiseFloor') return `${n.toFixed(0)} dBm`;
  if (metricKey === 'snr') return `${n.toFixed(0)} dB`;
  return `${n.toFixed(2)} Mbps`;
};

const formatTime = (timestamp) => {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
};

function getChartBounds(history, selectedRouter, metricKey, config) {
  const values = config.series.flatMap((series) => history
    .map((sample) => chartValue(metricKey, sample[selectedRouter]?.[series.key]))
    .filter((value) => value !== null && Number.isFinite(value)));

  const min = config.min;
  const max = config.max === null
    ? Math.max(1, ...values) * 1.12
    : config.max;

  return { min, max, hasValues: values.length > 0 };
}

function makeLineSegments(history, selectedRouter, metricKey, seriesKey, bounds, timeRange) {
  const points = [];
  let segment = [];

  history.forEach((sample) => {
    const timestamp = new Date(sample.timestamp).getTime();
    const raw = sample[selectedRouter]?.[seriesKey];
    const value = chartValue(metricKey, raw);

    if (!Number.isFinite(timestamp) || value === null || !Number.isFinite(value)) {
      if (segment.length) points.push(segment);
      segment = [];
      return;
    }

    const timeSpan = Math.max(1, timeRange.end - timeRange.start);
    const x = CHART.left + ((timestamp - timeRange.start) / timeSpan) * PLOT_WIDTH;
    const y = CHART.top + ((bounds.max - value) / (bounds.max - bounds.min)) * PLOT_HEIGHT;
    segment.push({ x, y, value, timestamp });
  });

  if (segment.length) points.push(segment);
  return points;
}

export default function RadioLinkPanel() {
  const { radioLink, radioLinkStatus } = useRover();
  const [history, setHistory] = useState([]);
  const [selectedRouter, setSelectedRouter] = useState('mantbox');
  const [selectedMetric, setSelectedMetric] = useState('signal');
  const [hover, setHover] = useState(null);
 

  const routers = radioLink?.routers || {};
  const mantbox = routers.mantbox || null;
  const netmetal = routers.netmetal || null;

  // Store one sample per distinct collector timestamp and retain up to MAX_HISTORY samples.
  useEffect(() => {
    if (!radioLink) return;

    const timestamp = radioLink.updated_at || new Date().toISOString();
    const sample = {
      timestamp,
      mantbox: makeSample(mantbox),
      netmetal: makeSample(netmetal),
    };

    setHistory((previous) => {
      if (previous.some((item) => item.timestamp === timestamp)) return previous;
      return [...previous, sample].slice(-MAX_HISTORY);
    });
  }, [radioLink, mantbox, netmetal]);

  const config = useMemo(() => metricConfig(selectedMetric), [selectedMetric]);
  const bounds = useMemo(
    () => getChartBounds(history, selectedRouter, selectedMetric, config),
    [history, selectedRouter, selectedMetric, config],
  );

  const timeRange = useMemo(() => {
    const times = history
      .map((sample) => new Date(sample.timestamp).getTime())
      .filter(Number.isFinite);
    if (!times.length) {
      const now = Date.now();
      return { start: now - 1000, end: now };
    }
    const start = Math.min(...times);
    const end = Math.max(...times);
    return end === start ? { start: start - 500, end: end + 500 } : { start, end };
  }, [history]);

  const renderedSeries = useMemo(() => config.series.map((series) => ({
    ...series,
    segments: makeLineSegments(history, selectedRouter, selectedMetric, series.key, bounds, timeRange),
  })), [config, history, selectedRouter, selectedMetric, bounds, timeRange]);

  const yTicks = useMemo(() => Array.from({ length: 5 }, (_, index) => (
    bounds.max - ((bounds.max - bounds.min) * index / 4)
  )), [bounds]);

  const xTicks = useMemo(() => Array.from({ length: 5 }, (_, index) => (
    timeRange.start + ((timeRange.end - timeRange.start) * index / 4)
  )), [timeRange]);

  const lastUpdated = radioLink?.updated_at
    ? new Date(radioLink.updated_at).toLocaleTimeString()
    : 'Waiting for first poll';
  const sampleIntervalMs = numberOrNull(radioLink?.sample_interval_ms);
  const pollDurationMs = numberOrNull(radioLink?.poll_duration_ms);
  const actualIntervalMs = numberOrNull(radioLink?.actual_interval_ms);
  const noiseFloorUnavailable = selectedMetric === 'noiseFloor' && !bounds.hasValues;
  const snrUnavailable = selectedMetric === 'snr' && !bounds.hasValues;

  const handleChartMove = (event) => {
    if (!history.length) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width) return;

    const pointerX = ((event.clientX - rect.left) / rect.width) * CHART.width;
    const plotRatio = Math.max(0, Math.min(1, (pointerX - CHART.left) / PLOT_WIDTH));
    const targetTime = timeRange.start + plotRatio * (timeRange.end - timeRange.start);

    let nearestIndex = 0;
    let nearestDistance = Infinity;
    history.forEach((sample, index) => {
      const sampleTime = new Date(sample.timestamp).getTime();
      const distance = Math.abs(sampleTime - targetTime);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });

    const current = history[nearestIndex];
    const pointTime = new Date(current.timestamp).getTime();
    const pointRatio = (pointTime - timeRange.start) / Math.max(1, timeRange.end - timeRange.start);
    const x = CHART.left + pointRatio * PLOT_WIDTH;
    setHover({ index: nearestIndex, x });
  };

  const hoverSample = hover ? history[hover.index] : null;

  if (!radioLink) {
    return (
      <section className="hud-panel p-5 border border-space-800 bg-[#0b0f19]/70">
        <div className="text-xs text-cyber-amber font-black tracking-widest">[02_RADIO_LINK_MONITORING]</div>
        <div className="text-sm text-slate-400 mt-4">
          {radioLinkStatus === 'offline'
            ? 'Radio API unavailable. Check the FastAPI backend.'
            : 'Waiting for first MikroTik data sample...'}
        </div>
      </section>
    );
  }

  return (
    <section className="hud-panel p-4 border border-space-800 bg-[#0b0f19]/70 relative overflow-hidden font-mono">
      <div className="flex flex-wrap justify-between items-center gap-3 border-b border-space-800/70 pb-3 mb-4">
        <div>
          <div className="text-[10px] text-cyber-amber/70 tracking-[0.2em] font-bold">[02_COMMUNICATIONS]</div>
          <h2 className="text-sm text-cyber-amber font-black tracking-widest mt-1">RADIO LINK MONITORING</h2>
          <div className="text-[8px] text-slate-500 mt-1">
            MIKROTIK REST API // TARGET {sampleIntervalMs === null ? '—' : `${sampleIntervalMs.toFixed(0)} ms`}
            {actualIntervalMs === null ? '' : ` // ACTUAL ${actualIntervalMs.toFixed(0)} ms`}
            {pollDurationMs === null ? '' : ` // RADIO REQUESTS ${pollDurationMs.toFixed(0)} ms`}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-[9px] font-black ${radioLinkStatus === 'online' ? 'text-emerald-400' : 'text-cyber-red'}`}>
            ● COLLECTOR {String(radioLinkStatus || 'unknown').toUpperCase()}
          </div>
          <div className="text-[8px] text-slate-500 mt-1">UPDATED: {lastUpdated}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <RouterCard router={mantbox} title="mANTBox // ACCESS POINT" />
        <RouterCard router={netmetal} title="NetMetal // STATION" />
      </div>

      <div className="mt-4 bg-[#060608]/75 border border-space-850 rounded-lg p-3">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <div className="text-[10px] text-cyber-amber font-black tracking-widest">LIVE RADIO HISTORY</div>
            <div className="text-[8px] text-slate-500 mt-1">
              LAST {history.length} SAMPLES // UP TO {MAX_HISTORY} SAMPLES // BROWSER-SESSION HISTORY
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {[
              { key: 'mantbox', label: 'mANTBOX' },
              { key: 'netmetal', label: 'NETMETAL' },
            ].map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => { setSelectedRouter(option.key); setHover(null); }}
                aria-pressed={selectedRouter === option.key}
                className={`px-2 py-1 text-[8px] font-bold rounded border ${
                  selectedRouter === option.key
                    ? 'text-cyber-amber border-cyber-amber bg-cyber-amber/10'
                    : 'text-slate-500 border-space-800 hover:text-slate-300'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5 mb-3">
          {METRICS.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => { setSelectedMetric(option.key); setHover(null); }}
              aria-pressed={selectedMetric === option.key}
              className={`px-2.5 py-1.5 text-[8px] font-bold rounded border ${
                selectedMetric === option.key
                  ? 'text-cyan-300 border-cyan-500/50 bg-cyan-500/10'
                  : 'text-slate-500 border-space-800 hover:text-slate-300'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="relative w-full bg-[#030407] border border-space-850 rounded overflow-hidden">
          <svg
            className="block w-full h-[230px]"
            viewBox={`0 0 ${CHART.width} ${CHART.height}`}
            preserveAspectRatio="none"
            onMouseMove={handleChartMove}
            onMouseLeave={() => setHover(null)}
            role="img"
            aria-label={`${selectedMetric} history chart for ${selectedRouter}`}
          >
            {yTicks.map((tick, index) => {
              const y = CHART.top + (index / 4) * PLOT_HEIGHT;
              return (
                <g key={`y-${index}`}>
                  <line x1={CHART.left} y1={y} x2={CHART.width - CHART.right} y2={y} stroke="#273244" strokeWidth="1" strokeDasharray="4 5" />
                  <text x={CHART.left - 9} y={y + 3} textAnchor="end" fill="#94a3b8" fontSize="10">
                    {tick.toFixed(selectedMetric === 'throughput' || selectedMetric === 'linkRate' ? 1 : 0)}
                  </text>
                </g>
              );
            })}

            {xTicks.map((tick, index) => {
              const x = CHART.left + (index / 4) * PLOT_WIDTH;
              return (
                <g key={`x-${index}`}>
                  <line x1={x} y1={CHART.top} x2={x} y2={CHART.height - CHART.bottom} stroke="#1e293b" strokeWidth="0.7" />
                  <text x={x} y={CHART.height - 17} textAnchor="middle" fill="#94a3b8" fontSize="10">
                    {formatTime(tick)}
                  </text>
                </g>
              );
            })}

            {renderedSeries.flatMap((series) => series.segments.map((segment, segmentIndex) => (
              <polyline
                key={`${series.key}-${segmentIndex}`}
                fill="none"
                stroke={series.color}
                strokeWidth="2.4"
                strokeLinejoin="round"
                strokeLinecap="round"
                points={segment.map((point) => `${point.x},${point.y}`).join(' ')}
              />
            )))}

            {hoverSample && (
              <line
                x1={hover.x}
                y1={CHART.top}
                x2={hover.x}
                y2={CHART.height - CHART.bottom}
                stroke="#e2e8f0"
                strokeWidth="1"
                strokeDasharray="3 4"
                opacity="0.7"
              />
            )}

            <text x={CHART.left} y={CHART.height - 3} fill="#64748b" fontSize="9">TIME</text>
            <text x="10" y="12" fill="#64748b" fontSize="9">{config.unit}</text>
          </svg>

          {hoverSample && (
            <div
              className="pointer-events-none absolute top-2 z-10 min-w-[150px] rounded border border-space-700 bg-[#080c14]/95 px-3 py-2 shadow-xl"
              style={{
                left: `${Math.max(8, Math.min(78, (hover.x / CHART.width) * 100))}%`,
              }}
            >
              <div className="text-[9px] text-slate-400 mb-1">
                {new Date(hoverSample.timestamp).toLocaleString()}
              </div>
              {config.series.map((series) => (
                <div key={series.key} className="flex items-center justify-between gap-3 text-[9px]">
                  <span style={{ color: series.color }}>{series.label}</span>
                  <strong className="text-slate-100 tabular-nums">
                    {formatChartValue(selectedMetric, hoverSample[selectedRouter]?.[series.key])}
                  </strong>
                </div>
              ))}
              <div className="text-[8px] text-slate-500 mt-1">
                LINK: {hoverSample[selectedRouter]?.linkStatus?.toUpperCase() || 'UNKNOWN'}
              </div>
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-4 mt-3">
          {config.series.map((series) => (
            <div key={series.key} className="flex items-center gap-1.5">
              <span className="w-3 h-0.5" style={{ backgroundColor: series.color }} />
              <span className="text-[8px] text-slate-400 font-bold">{series.label.toUpperCase()}</span>
            </div>
          ))}
          <span className="text-[8px] text-slate-500 ml-auto">Y: {config.unit} // X: LOCAL TIME</span>
        </div>

        {!bounds.hasValues && (
          <div className="text-[9px] text-amber-300/90 mt-3 border-t border-space-800 pt-2">
            {noiseFloorUnavailable
              ? 'NOISE FLOOR DATA UNAVAILABLE: RouterOS /interface/wifi registration-table does not provide a live noise-floor field. Frequency-scan reports nf but disconnects associated clients; it is not used for live polling.'
              : snrUnavailable
                ? 'SNR DATA UNAVAILABLE: SNR needs a valid noise-floor measurement at the same radio and approximately the same time as RSSI. No supported live source is currently configured.'
                : 'No valid measurements are available for this graph yet. Check the selected router API and wireless registration status.'}
          </div>
        )}

        {history.length < 2 && (
          <div className="text-[8px] text-slate-500 mt-2">Collecting samples. The graph will develop as new readings arrive.</div>
        )}
      </div>
    </section>
  );
}
