
import { useState } from 'react';
import { useRover } from '../context/RoverContext';

import CockpitLayout from './CockpitLayout';
import NodeStatusStrip from '../components/system/NodeStatusStrip';
import SystemDiagnostics from '../components/system/SystemDiagnostics';
import GpsPanel from '../components/system/GpsPanel';
import RadioLinkPanel from '../components/system/RadioLinkPanel';

import ImuPanel from '../components/telemetry/ImuPanel';
import AnemometerPanel from '../components/telemetry/AnemometerPanel';
import DriveMotorsPanel from '../components/telemetry/DriveMotorsPanel';
import ArmMotorsPanel from '../components/telemetry/ArmMotorsPanel';

import CameraFrame from '../components/video/CameraFrame';
import ActionBar from '../components/controls/ActionBar';

/**
 * Rover Mission Control - Primary Operator View
 *
 * Layout:
 * 1. Node Status Strip
 * 2. Full-width MikroTik Radio Link Monitoring
 * 3. Main Rover Cockpit
 *    - Left: Communications, GPS, IMU, Anemometer
 *    - Center: Live Camera Viewports
 *    - Right: Drive Motors and Robotic Arm
 * 4. Bottom Action Bar
 */

export default function PrimaryOperatorView() {

  const { activeCamera, cameras } = useRover();

  const [secondaryCamId, setSecondaryCamId] = useState('arm_cam');

  const secondaryOptions = [
    { id: 'front_cam', name: 'Front Camera' },
    { id: 'rear_cam', name: 'Rear Camera' },
    { id: 'arm_cam', name: 'Arm Camera' },
    { id: 'science_cam', name: 'Science Camera' },
    { id: 'thermal_cam', name: 'Thermal Camera' },
    { id: 'nav_cam', name: 'Navigation Camera' }
  ];

  const secondaryCamera =
    cameras.find(c => c.id === secondaryCamId) || cameras[2];

  return (
    <div className="w-full flex flex-col gap-4 font-mono select-none">

      {/* 1. NODE STATUS HEARTBEATS */}
      <NodeStatusStrip />

      <CockpitLayout panels={{
        radio: <RadioLinkPanel />,
        diagnostics: <SystemDiagnostics />,
        gps: <GpsPanel />,
        imu: <ImuPanel />,
        wind: <AnemometerPanel />,
        primary: (
          <CameraFrame
            camera={activeCamera}
            isMinified={false}
            className="flex-1"
          />
        ),
        secondary: (
          <CameraFrame
            camera={secondaryCamera}
            isMinified={false}
            className="flex-1"
            headerSelector={(
              <select
                value={secondaryCamId}
                onChange={(e) => setSecondaryCamId(e.target.value)}
                className="bg-[#060608]/90 text-cyber-amber border border-space-800 rounded px-1.5 py-0.5 focus:outline-none focus:border-cyber-amber cursor-pointer uppercase text-[8px] font-black font-mono ml-1"
              >
                {secondaryOptions.map(opt => (
                  <option
                    key={opt.id}
                    value={opt.id}
                    className="bg-space-950 text-slate-350 font-mono"
                  >
                    ▼ {opt.name.toUpperCase()}
                  </option>
                ))}
              </select>
            )}
          />
        ),
        drive: <DriveMotorsPanel />,
        arm: <ArmMotorsPanel />,
      }} />

      {/* 4. BOTTOM DOCKED ACTION CONTROLS */}
      <ActionBar />

    </div>
  );
}
