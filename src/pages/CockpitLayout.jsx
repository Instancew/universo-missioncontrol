import { useState } from 'react';
import { GripVertical } from 'lucide-react';

const slotStyles = {
  radio: 'xl:col-span-5 xl:row-start-1',
  diagnostics: 'xl:col-start-1 xl:row-start-2',
  gps: 'xl:col-start-1 xl:row-start-3',
  imu: 'xl:col-start-1 xl:row-start-4',
  wind: 'xl:col-start-1 xl:row-start-5',
  primary: 'xl:col-start-2 xl:col-span-3 xl:row-start-2 xl:row-span-2',
  secondary: 'xl:col-start-2 xl:col-span-3 xl:row-start-4 xl:row-span-2',
  drive: 'xl:col-start-5 xl:row-start-2 xl:row-span-2',
  arm: 'xl:col-start-5 xl:row-start-4 xl:row-span-2',
};
const defaultOrder = Object.keys(slotStyles);
const storageKey = 'irc.operations.panel-order.v1';
const panelNames = {
  radio: 'MikroTik radio link',
  diagnostics: 'System diagnostics', gps: 'GPS', imu: 'IMU', wind: 'Anemometer',
  primary: 'Primary camera', secondary: 'Secondary camera', drive: 'Drive motors', arm: 'Arm motors',
};

function readOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    if (Array.isArray(saved) && !saved.includes('radio')) saved.unshift('radio');
    if (Array.isArray(saved) && saved.length === defaultOrder.length &&
        defaultOrder.every(id => saved.includes(id))) return saved;
  } catch {
    // Use the standard cockpit when storage is unavailable or unreadable.
  }
  return defaultOrder;
}

const buttonStyle = 'rounded border border-space-800 bg-space-950 px-3 py-1.5 text-xs text-slate-300 hover:border-cyber-amber focus-visible:outline-cyber-amber';

export default function CockpitLayout({ panels }) {
  const [order, setOrder] = useState(readOrder);
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState(null);
  const [dragged, setDragged] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [storageUnavailable, setStorageUnavailable] = useState(false);

  function clearSelection() {
    setSelected(null);
    setDragged(null);
    setHovered(null);
  }

  function saveOrder(next) {
    setOrder(next);
    clearSelection();
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
      setStorageUnavailable(false);
    } catch {
      setStorageUnavailable(true);
    }
  }

  function swap(source, target) {
    if (source === target) return clearSelection();
    const next = order.slice();
    const from = next.indexOf(source);
    const to = next.indexOf(target);
    if (from < 0 || to < 0) return;
    next[from] = target;
    next[to] = source;
    saveOrder(next);
  }

  function renderPanel(slot) {
    const id = order[defaultOrder.indexOf(slot)];
    const camera = id === 'primary' || id === 'secondary';
    const highlight = hovered === id || selected === id;
    return (
      <section key={id} data-panel={id} aria-label={panelNames[id]}
        className={`min-w-0 flex flex-col rounded-lg ${slotStyles[slot]} ${camera ? 'self-stretch min-h-52' : ''} ${highlight ? 'ring-2 ring-cyber-amber' : ''}`}
        onDragOver={event => {
          if (!editing || !dragged) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = 'move';
          setHovered(id);
        }}
        onDragLeave={event => {
          if (!event.currentTarget.contains(event.relatedTarget)) setHovered(null);
        }}
        onDrop={event => {
          if (!editing || !dragged) return;
          event.preventDefault();
          swap(dragged, id);
        }}>
        {editing && (
          <button type="button" draggable aria-label={`Move ${panelNames[id]}`} aria-pressed={selected === id}
            className="flex items-center gap-1.5 w-full cursor-grab active:cursor-grabbing rounded-t border border-space-800 bg-space-900 px-2 py-1 text-xs text-cyber-amber focus-visible:outline-cyber-amber"
            onDragStart={event => {
              event.dataTransfer.effectAllowed = 'move';
              event.dataTransfer.setData('text/plain', id);
              event.dataTransfer.setDragImage(event.currentTarget, 12, 10);
              setSelected(null);
              setDragged(id);
            }}
            onDragEnd={clearSelection}
            onClick={() => selected ? swap(selected, id) : setSelected(id)}>
            <GripVertical size={16} aria-hidden="true" />{panelNames[id]}
          </button>
        )}
        {panels[id]}
      </section>
    );
  }

  return (
    <div className="flex flex-col gap-2" onKeyDown={event => {
      if (editing && event.key === 'Escape') clearSelection();
    }}>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {editing && <>
          <span role="status" className="mr-auto text-xs text-slate-400">
            {selected ? `Choose a panel to swap with ${panelNames[selected]}.` : 'Drag a handle onto another panel, or select two handles to swap.'}
          </span>
          <button type="button" className={buttonStyle} onClick={() => saveOrder(defaultOrder)}>Reset layout</button>
        </>}
        <button type="button" className={buttonStyle} aria-pressed={editing}
          onClick={() => { clearSelection(); setEditing(!editing); }}>
          {editing ? 'Done' : 'Edit layout'}
        </button>
      </div>
      {storageUnavailable && <p role="status" className="text-xs text-cyber-amber">Browser storage is unavailable. This layout applies to the current view.</p>}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 w-full items-start">
        {defaultOrder.map(renderPanel)}
      </div>
    </div>
  );
}
