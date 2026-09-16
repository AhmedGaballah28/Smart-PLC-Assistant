import { parameters, sensorSeries } from "./data.js";

async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || data.stderr || `Request failed: ${response.status}`);
  }
  return data;
}

export class TelemetryService {
  constructor() {
    this.tick = 0;
  }

  snapshot() {
    this.tick += 1;
    return parameters.map((parameter, index) => {
      const wave = Math.sin((this.tick + index) / 3);
      const delta = Number((wave * (index + 1) * 0.35).toFixed(1));
      return {
        ...parameter,
        value: Number((parameter.value + delta).toFixed(1)),
      };
    });
  }

  trends() {
    return sensorSeries;
  }
}

export class IncidentService {
  constructor() {
    this.snapshot = null;
  }

  async loadDashboard() {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`Dashboard API failed with ${response.status}`);
    this.snapshot = await response.json();
    return this.snapshot;
  }

  async submitHumanDecision(decision, details = {}) {
    const result = await postJson("/api/human-decision", { decision, ...details });
    this.snapshot = result.snapshot || this.snapshot;
    return result;
  }

  async startProject() {
    return postJson("/api/start-project");
  }

  async stopProject() {
    return postJson("/api/stop-project");
  }

  async injectFault(payload) {
    return postJson("/api/inject-fault", payload);
  }

  activeAlerts() {
    const liveAlerts = this.snapshot?.alerts || [];
    if (!liveAlerts.length) return [];
    return liveAlerts.map((alert) => ({
      severity: alert.severity,
      station: [alert.line_id, alert.station_id].filter(Boolean).join(" / ") || "Factory",
      title: alert.alert_type || "Agent alert",
      diagnosis: alert.message,
      confidence: 82,
      created_at: alert.created_at,
    }));
  }

  diagnoses() {
    return this.snapshot?.diagnoses || [];
  }

  logEntries() {
    const events = this.snapshot?.events || [];
    if (!events.length) return [];
    return events.map((event) => [
      new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      event.source_agent || event.stage,
      `${event.event_type} on ${event.stage}: ${event.severity}`,
    ]);
  }

  latestIncident() {
    return this.snapshot?.latest_incident || null;
  }

  approvals() {
    return this.snapshot?.approvals || [];
  }

  simulations() {
    return this.snapshot?.simulations || [];
  }

  heartbeats() {
    return this.snapshot?.heartbeats || [];
  }

  lineHealth() {
    return this.snapshot?.line_health || [];
  }

  repairProposals() {
    return this.snapshot?.repair_proposals || [];
  }

  validations() {
    return this.snapshot?.validation_results || [];
  }

  isRunning() {
    return Boolean(this.snapshot?.is_running);
  }

  health() {
    return this.snapshot?.health || { healthy: false, table_count: 0 };
  }

  activeNode() {
    return this.snapshot?.active_node || "diagnose";
  }

  raw() {
    return this.snapshot || {};
  }
}

export class WorkflowService {
  constructor(nodes) {
    this.nodes = nodes;
    this.index = 1;
  }

  current() {
    return this.nodes[this.index]?.id || "diagnose";
  }

  setActiveNode(nodeId) {
    const nodeIndex = this.nodes.findIndex((node) => node.id === nodeId);
    if (nodeIndex >= 0) this.index = nodeIndex;
  }

  advance(decision = "APPROVE") {
    const normalized = decision.toUpperCase();
    const order = normalized === "REJECT"
      ? ["diagnose", "repair", "validate", "inject_feedback", "repair"]
      : ["diagnose", "repair", "validate", "simulate", "human", "execute", "report", "end"];
    const currentIndex = order.indexOf(this.current());
    this.index = this.nodes.findIndex((node) => node.id === order[(currentIndex + 1) % order.length]);
    if (this.index < 0) this.index = 1;
    return this.current();
  }
}
