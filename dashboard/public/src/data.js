export const sensorSeries = {
  temperature: [47, 49, 51, 54, 58, 56, 53, 55, 57, 59, 61, 58],
  speed: [1480, 1475, 1460, 1440, 1415, 1380, 1395, 1420, 1445, 1462, 1472, 1481],
  vibration: [18, 21, 24, 28, 35, 41, 38, 34, 31, 29, 27, 25],
  energy: [2.1, 2.4, 2.5, 2.8, 3.1, 3.4, 3.2, 3.0, 2.7, 2.6, 2.5, 2.3],
};

export const parameters = [
  { label: "Motor Temp", value: 58, unit: "C", min: 20, max: 80, state: "warning" },
  { label: "Motor Speed", value: 1468, unit: "RPM", min: 1100, max: 1500, state: "good" },
  { label: "Vibration", value: 31, unit: "mm/s", min: 0, max: 70, state: "good" },
  { label: "Cycle Time", value: 6.4, unit: "s", min: 3, max: 12, state: "warning" },
  { label: "Power", value: 2.8, unit: "kW", min: 0, max: 5, state: "good" },
  { label: "Quality", value: 97.2, unit: "%", min: 80, max: 100, state: "good" },
];

export const navItems = [
  { id: "monitoring", label: "Live Monitoring", icon: "LM" },
  { id: "alerts", label: "Alerts & Diagnosis", icon: "AD" },
  { id: "twin", label: "Digital Twin", icon: "DT" },
  { id: "simulation", label: "Simulation Results", icon: "SR" },
  { id: "analytics", label: "Analytics", icon: "AN" },
  { id: "agents", label: "Agent Activity Log", icon: "AL" },
  { id: "faults", label: "Fault Injection", icon: "FI" },
  { id: "settings", label: "Settings", icon: "ST" },
];

export const agentNodes = [
  { id: "start", label: "start" },
  { id: "diagnose", label: "diagnose" },
  { id: "repair", label: "repair" },
  { id: "validate", label: "validate" },
  { id: "simulate", label: "simulate" },
  { id: "human", label: "human", kind: "human-gate" },
  { id: "execute", label: "execute" },
  { id: "report", label: "report" },
  { id: "end", label: "end" },
];

export const faultScenarios = [
  {
    id: 1,
    name: "Thermal Cascade",
    subtitle: "Cooling system failure",
    story: "Line 1 chiller degradation causes machining heat, then downstream inspection and handling delays.",
  },
  {
    id: 2,
    name: "Pneumatic Collapse",
    subtitle: "Contaminated compressed air",
    story: "Line 2 air quality failure affects grippers, cylinders, valves, and transfer actions.",
  },
  {
    id: 3,
    name: "Power Grid Instability",
    subtitle: "Shared voltage sag",
    story: "Both lines experience VFD ripple, sensor noise, and inspection instability from a common supply issue.",
  },
  {
    id: 4,
    name: "Mechanical Wear",
    subtitle: "End-of-shift chain reaction",
    story: "Line 1 belt slip, vibration, debris, and downstream sensor contamination cascade through the cell.",
  },
];
