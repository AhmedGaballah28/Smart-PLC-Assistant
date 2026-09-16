import { faultScenarios } from "./data.js";
import { confidenceMeter, gauge, lineChart, table } from "./components.js";

export const tabs = [
  { id: "monitoring", label: "Live Monitoring", render: renderMonitoring },
  { id: "alerts", label: "Alerts & Diagnosis", render: renderAlerts },
  { id: "twin", label: "Digital Twin", render: renderTwin },
  { id: "simulation", label: "Simulation Results", render: renderSimulation },
  { id: "analytics", label: "Analytics", render: renderAnalytics },
  { id: "agents", label: "Agent Activity Log", render: renderAgents },
  { id: "faults", label: "Fault Injection", render: renderFaults },
  { id: "settings", label: "Settings", render: renderSettings },
];

function sectionTitle(title, description) {
  return `<div class="section-title"><h2>${title}</h2><p>${description}</p></div>`;
}

function emptyState(title, message) {
  return `
    <article class="empty-state">
      <div class="empty-state-icon">•</div>
      <h3>${title}</h3>
      <p>${message}</p>
    </article>
  `;
}

function badge(value, fallback = "UNKNOWN") {
  return `<span class="incident-status-badge">${value || fallback}</span>`;
}

function renderMonitoring({ telemetry, incidents }) {
  const params = telemetry.snapshot();
  const trends = telemetry.trends();
  const health = incidents.health();
  const incident = incidents.latestIncident();
  const alerts = incidents.activeAlerts();
  const streamRows = incidents.logEntries().slice(0, 5);

  return `
    ${sectionTitle("Live Monitoring", "Realtime plant state, data freshness, and MQTT/agent stream.")}
    <div class="metric-grid">${params.map(gauge).join("")}</div>
    <div class="chart-grid-two">
      ${lineChart("Temperature", trends.temperature, "C")}
      ${lineChart("Speed", trends.speed, "RPM")}
      ${lineChart("Vibration", trends.vibration, "mm/s")}
    </div>
    <div class="split-panel">
      <article class="status-panel">
        <h3>System Status</h3>
        <div class="stacked-status">
          <span><i class="status-light ${health.healthy ? "green" : "red"}"></i> SQLite ${health.healthy ? "online" : "offline"}</span>
          <span><i class="status-light ${incidents.isRunning() ? "green" : "yellow"}"></i> Project ${incidents.isRunning() ? "running" : "not launched from dashboard"}</span>
          <span><i class="status-light ${alerts.length ? "yellow" : "green"}"></i> Active alerts: ${alerts.length}</span>
          <span><i class="status-light ${incident ? "yellow" : "green"}"></i> Incident: ${incident?.status || "idle"}</span>
        </div>
      </article>
      <article class="stream-panel">
        <h3>Agent / MQTT Stream</h3>
        ${streamRows.length ? streamRows.map(([time, agent, action]) => `<code>${time} ${agent}: ${action}</code>`).join("") : `<code>No agent events recorded yet.</code>`}
      </article>
    </div>
  `;
}

function renderAlerts({ incidents }) {
  const diagnoses = incidents.diagnoses();
  const approvals = incidents.approvals();
  const latestDiagnosis = diagnoses[0];
  const activeAlerts = incidents.activeAlerts();

  return `
    ${sectionTitle("Alerts & Diagnosis", "Explainable AI output with human approval controls.")}
    <div class="approval-banner ${approvals.length ? "armed" : ""}">
      <div>
        <span>${approvals.length ? "HUMAN GATE OPEN" : "WAITING FOR APPROVAL REQUEST"}</span>
        <strong>${approvals[0]?.request_id || "No pending approval in SQLite"}</strong>
      </div>
      ${approvals.length ? `<div class="approval-actions">
        <button data-decision="APPROVE">Approve</button>
        <button data-decision="REJECT">Reject</button>
        <button data-decision="MODIFY">Modify</button>
      </div>` : ""}
    </div>
    ${latestDiagnosis ? `
      <article class="xai-panel">
        <span class="severity">${latestDiagnosis.severity}</span>
        <h3>Explainable AI Diagnosis</h3>
        <p>${latestDiagnosis.root_cause}</p>
        <p>${latestDiagnosis.reasoning || latestDiagnosis.recommended_action || "The diagnostic agent saved a result without extended reasoning."}</p>
        <div class="confidence-bar-container"><span>Confidence</span>${confidenceMeter(latestDiagnosis.confidence || 0)}</div>
      </article>
    ` : ""}
    <div class="alert-list">
      ${activeAlerts.length ? activeAlerts.map((alert) => `
        <article class="alert-card ${alert.severity}">
          <div class="alert-card-info">
            <span class="severity">${alert.severity}</span>
            <h3>${alert.title}</h3>
            <p>${alert.station}: ${alert.diagnosis}</p>
            ${confidenceMeter(alert.confidence)}
          </div>
        </article>
      `).join("") : emptyState("No active alerts", "The database is clean. Monitor Agent alerts will appear here as soon as they are written to SQLite.")}
    </div>
  `;
}

function renderTwin({ incidents }) {
  const rows = incidents.lineHealth();
  const tableRows = rows.map((row) => [
    row.line_id,
    row.overall_health,
    row.total_produced,
    `${Number(row.total_rate_per_min || 0).toFixed(2)} / min`,
    row.active_fault_count,
    row.alert_count,
  ]);

  return `
    ${sectionTitle("Digital Twin", "Current line health from aggregator snapshots and latest simulated impact.")}
    ${tableRows.length ? table(["Line", "Health", "Produced", "Rate", "Faults", "Alerts"], tableRows) : emptyState("No digital twin snapshots", "Start run_twin.py and realtime_aggregator.py to populate line_health_snapshots.")}
    <div class="scenario-grid">
      ${rows.slice(0, 3).map((row) => `
        <article class="scenario-card">
          <h3>${row.line_id}</h3>
          <div class="before-after ${row.active_fault_count ? "warning" : "good"}">
            ${row.overall_health}
            <small>${row.total_produced} produced · ${row.alert_count} alerts</small>
          </div>
        </article>
      `).join("") || `
        <article class="scenario-card"><h3>Current State</h3><div class="before-after warning">Awaiting telemetry<small>No line health rows yet</small></div></article>
        <article class="scenario-card"><h3>Simulated State</h3><div class="before-after">Awaiting simulation<small>No simulation rows yet</small></div></article>
        <article class="scenario-card"><h3>Scenario Tool</h3><select><option>Start the twin to enable comparisons</option></select></article>
      `}
    </div>
  `;
}

function renderSimulation({ incidents }) {
  const simulations = incidents.simulations();
  const validations = incidents.validations();
  const proposals = incidents.repairProposals();

  return `
    ${sectionTitle("Simulation Results", "Validation verdicts, repair proposals, and predicted operational deltas.")}
    <div class="kpi-grid">
      <article><span>Simulations</span><strong>${simulations.length}</strong></article>
      <article><span>Validations</span><strong>${validations.length}</strong></article>
      <article><span>Repair Proposals</span><strong>${proposals.length}</strong></article>
      <article><span>Latest Verdict</span><strong>${simulations[0]?.go_no_go || validations[0]?.verdict || "N/A"}</strong></article>
    </div>
    ${simulations.length ? table(
      ["Correlation", "Go / No-Go", "Confidence", "Cycle Δ", "Pass Rate Δ", "Throughput Δ", "Risk Δ"],
      simulations.map((sim) => [
        sim.correlation_id,
        sim.go_no_go,
        `${Math.round((sim.confidence || 0) * 100)}%`,
        sim.predicted_cycle_time_delta ?? "N/A",
        sim.predicted_pass_rate_delta ?? "N/A",
        sim.predicted_throughput_delta ?? "N/A",
        sim.predicted_fault_risk_delta ?? "N/A",
      ]),
    ) : emptyState("No simulation results", "Simulation Agent results will appear here after validation passes.")}
    ${proposals.length ? `<div class="scenario-grid">
      ${proposals.slice(0, 3).map((proposal) => `
        <article class="scenario-card">
          <h3>Proposal v${proposal.proposal_version}</h3>
          <p>${proposal.summary || "No summary attached."}</p>
          <small>${proposal.options?.length || 0} options · ${proposal.model_name || "model unknown"}</small>
        </article>
      `).join("")}
    </div>` : ""}
  `;
}

function renderAnalytics({ telemetry, incidents }) {
  const trends = telemetry.trends();
  const lineHealth = incidents.lineHealth();
  const events = incidents.raw().events || [];
  const produced = lineHealth.reduce((sum, row) => sum + Number(row.total_produced || 0), 0);
  const rate = lineHealth.reduce((sum, row) => sum + Number(row.total_rate_per_min || 0), 0);
  const faults = lineHealth.reduce((sum, row) => sum + Number(row.active_fault_count || 0), 0);
  const alerts = incidents.activeAlerts().length;

  return `
    ${sectionTitle("Analytics", "OEE-adjacent production indicators, event frequency, and energy profile.")}
    <div class="kpi-grid">
      <article><span>Total Produced</span><strong>${produced}</strong></article>
      <article><span>Total Rate</span><strong>${rate.toFixed(1)}</strong></article>
      <article><span>Active Faults</span><strong>${faults}</strong></article>
      <article><span>Open Alerts</span><strong>${alerts}</strong></article>
    </div>
    <div class="chart-grid-two">
      ${lineChart("Energy Consumption", trends.energy, "kW")}
      ${lineChart("Event Frequency", events.length ? events.slice(0, 12).map((_, index) => index + 1) : [0, 0, 0, 0], "events")}
    </div>
  `;
}

function renderAgents({ incidents }) {
  const health = incidents.health();
  const incident = incidents.latestIncident();
  const heartbeats = incidents.heartbeats();
  const logs = incidents.logEntries();

  return `
    ${sectionTitle("Agent Activity Log", "Chronological audit trail, heartbeats, and current incident state.")}
    <div class="agent-summary">
      <article><span>SQLite</span><strong>${health.healthy ? "ONLINE" : "OFFLINE"}</strong><small>${health.table_count} tables</small></article>
      <article><span>Incident</span><strong>${incident?.status || "IDLE"}</strong><small>${incident?.correlation_id || "No active incident"}</small></article>
      <article><span>Heartbeats</span><strong>${heartbeats.length}</strong><small>latest agent pings</small></article>
    </div>
    ${heartbeats.length ? table(["Agent", "Status", "Instance", "Version", "Last Seen"], heartbeats.map((beat) => [
      beat.agent_name,
      beat.status,
      beat.instance_id || "default",
      beat.version || "N/A",
      new Date(beat.created_at).toLocaleString(),
    ])) : ""}
    ${logs.length ? `<ol class="timeline">
      ${logs.map(([time, agent, action]) => `<li><time>${time}</time><strong>${agent}</strong><span>${action}</span></li>`).join("")}
    </ol>` : emptyState("No agent events yet", "Incident events will stream here after the monitor and supervisor agents write to SQLite.")}
  `;
}

function renderFaults() {
  return `
    ${sectionTitle("Fault Injection", "Run real MQTT fault injections through runners/inject_faults.py.")}
    <div class="fault-cards-grid">
      ${faultScenarios.map((scenario) => `
        <article class="fault-scenario-card">
          <div class="fault-scenario-card-header">
            <h3>${scenario.name}</h3>
            <p>${scenario.subtitle}</p>
            <p>${scenario.story}</p>
          </div>
          <div class="fault-scenario-card-footer">
            <span>Scenario ${scenario.id}</span>
            <button class="fault-scenario-btn" data-fault-action="scenario" data-scenario="${scenario.id}">Run Scenario</button>
          </div>
        </article>
      `).join("")}
    </div>
    <div class="manual-fault-panel">
      <h3>Manual Fault Command</h3>
      <div class="manual-fault-grid">
        <div class="command-input-container">
          <label for="faultCommandInput">Command format: &lt;line&gt;&lt;station&gt;f&lt;fault&gt; &lt;severity&gt;</label>
          <div class="command-input-wrapper">
            <span class="command-prefix">py inject_faults.py --cmd</span>
            <input class="command-input" id="faultCommandInput" value="12f4 3" />
          </div>
        </div>
        <button class="inject-btn" data-fault-action="command">Inject</button>
      </div>
      <div class="fault-panel-controls">
        <button class="interactive-menu-btn" data-fault-action="interactive">Open Interactive Menu</button>
        <button class="clear-faults-btn" data-fault-action="clear">Clear All Faults</button>
      </div>
      <div class="quick-ref">
        <p>Quick reference</p>
        <ul>
          <li>Line: 1 or 2</li>
          <li>Stations: A, B, 1, 2, 3, 6, 7, 8, 9</li>
          <li>Example: 12f4 3 = Line 1, Station 2, belt slip, severity 3</li>
          <li>Severity: 1-5</li>
        </ul>
      </div>
    </div>
  `;
}

function renderSettings() {
  const settings = JSON.parse(localStorage.getItem("smartPlcSettings") || "{}");
  return `
    ${sectionTitle("Settings", "Operator and system configuration persisted locally.")}
    <div class="settings-grid">
      <label>Autonomy Level
        <select id="settingAutonomy">
          ${["Human Approval Required", "Advisory Only", "Auto Execute Low Risk"].map((value) => `<option ${settings.autonomy === value ? "selected" : ""}>${value}</option>`).join("")}
        </select>
      </label>
      <label>Operator Skill Level
        <select id="settingSkill">
          ${["Senior Technician", "Operator", "Trainee"].map((value) => `<option ${settings.skill === value ? "selected" : ""}>${value}</option>`).join("")}
        </select>
      </label>
      <label class="checkbox-label"><input id="settingValidation" type="checkbox" ${settings.validation !== false ? "checked" : ""} /> Require command validation</label>
      <label class="checkbox-label"><input id="settingAudit" type="checkbox" ${settings.audit !== false ? "checked" : ""} /> Persist full audit trail</label>
    </div>
    <div class="settings-actions">
      <button class="settings-save-btn" data-settings-save>Save Settings</button>
    </div>
  `;
}
