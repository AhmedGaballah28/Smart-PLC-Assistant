import { agentNodes, navItems } from "./data.js";
import { renderFlow } from "./flow.js";
import { IncidentService, TelemetryService, WorkflowService } from "./services.js";
import { tabs } from "./tabs.js";

class DashboardApp {
  constructor() {
    this.telemetry = new TelemetryService();
    this.incidents = new IncidentService();
    this.workflow = new WorkflowService(agentNodes);
    this.activeTab = "monitoring";
    this.elements = {
      sidebar: document.querySelector("#sidebar"),
      sidebarNav: document.querySelector("#sidebarNav"),
      toggleSidebarBtn: document.querySelector("#toggleSidebarBtn"),
      tabPanel: document.querySelector("#tabPanel"),
      pipelineContainer: document.querySelector("#pipelineContainer"),
      advanceFlowBtn: document.querySelector("#advanceFlowBtn"),
      systemStatusPill: document.querySelector("#systemStatusPill"),
      incidentStatusBar: document.querySelector("#incidentStatusBar"),
      projectLauncherBtn: document.querySelector("#projectLauncherBtn"),
      toastContainer: document.querySelector("#toastContainer"),
    };
  }

  start() {
    this.bootstrap();
    this.bindEvents();
    window.setInterval(() => this.refreshLiveViews(), 4000);
  }

  async bootstrap() {
    this.renderNav();
    await this.refreshSnapshot();
    this.renderActiveTab();
    this.renderFlow();
  }

  bindEvents() {
    this.elements.sidebarNav.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-tab]");
      if (!button) return;
      this.activeTab = button.dataset.tab;
      this.renderNav();
      this.renderActiveTab();
    });

    this.elements.toggleSidebarBtn.addEventListener("click", () => {
      this.elements.sidebar.classList.toggle("collapsed");
    });

    this.elements.advanceFlowBtn.addEventListener("click", () => {
      this.workflow.advance("APPROVE");
      this.renderFlow();
      this.toast("Preview advanced locally. Live state refreshes from SQLite.", "warning");
    });

    this.elements.projectLauncherBtn.addEventListener("click", async () => {
      if (this.incidents.isRunning()) {
        await this.stopProject();
      } else {
        await this.startProject();
      }
    });

    this.elements.pipelineContainer.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-decision]");
      if (!button) return;
      await this.submitDecision(button, button.dataset.decision);
    });

    this.elements.tabPanel.addEventListener("click", async (event) => {
      const decisionButton = event.target.closest("button[data-decision]");
      if (decisionButton) {
        await this.submitDecision(decisionButton, decisionButton.dataset.decision);
        return;
      }

      const faultButton = event.target.closest("button[data-fault-action]");
      if (faultButton) {
        await this.handleFaultAction(faultButton);
        return;
      }

      const saveButton = event.target.closest("button[data-settings-save]");
      if (saveButton) {
        this.saveSettings();
      }
    });
  }

  async refreshSnapshot() {
    try {
      await this.incidents.loadDashboard();
      this.workflow.setActiveNode(this.incidents.activeNode());
      this.renderStatusPill();
      this.renderIncidentStatus();
      this.renderLauncher();
    } catch (error) {
      console.warn(error);
      this.renderStatusPill(false);
    }
  }

  async startProject() {
    const button = this.elements.projectLauncherBtn;
    button.disabled = true;
    button.className = "launcher-btn starting";
    button.querySelector(".launcher-text").textContent = "Starting services...";
    try {
      const result = await this.incidents.startProject();
      this.toast(`Project started. ${result.pids?.length || 0} services launched.`, "success");
      await this.refreshSnapshot();
    } catch (error) {
      this.toast(error.message, "danger");
    } finally {
      button.disabled = false;
      this.renderLauncher();
    }
  }

  async stopProject() {
    const button = this.elements.projectLauncherBtn;
    button.disabled = true;
    try {
      const result = await this.incidents.stopProject();
      this.toast(`Stopped: ${(result.terminated || []).join(", ") || result.message || "no recorded processes"}`, "success");
      await this.refreshSnapshot();
    } catch (error) {
      this.toast(error.message, "danger");
    } finally {
      button.disabled = false;
      this.renderLauncher();
    }
  }

  async submitDecision(button, decision) {
    button.disabled = true;
    try {
      await this.incidents.submitHumanDecision(decision, {
        reason: `Operator selected ${decision} from the dashboard.`,
      });
      await this.refreshSnapshot();
      this.toast(`${decision} decision saved to SQLite.`, "success");
    } catch (error) {
      console.error(error);
      this.workflow.advance(decision);
      this.toast(error.message, "danger");
    } finally {
      button.disabled = false;
      this.renderFlow();
      this.renderActiveTab();
    }
  }

  async handleFaultAction(button) {
    const action = button.dataset.faultAction;
    const payload = { action };
    if (action === "scenario") payload.scenario = Number(button.dataset.scenario);
    if (action === "command") payload.cmd = document.querySelector("#faultCommandInput")?.value?.trim();
    button.disabled = true;
    try {
      const result = await this.incidents.injectFault(payload);
      this.toast(result.message || "Fault command sent.", "success");
      await this.refreshSnapshot();
    } catch (error) {
      this.toast(error.message, "danger");
    } finally {
      button.disabled = false;
    }
  }

  saveSettings() {
    const settings = {
      autonomy: document.querySelector("#settingAutonomy")?.value,
      skill: document.querySelector("#settingSkill")?.value,
      validation: document.querySelector("#settingValidation")?.checked,
      audit: document.querySelector("#settingAudit")?.checked,
    };
    localStorage.setItem("smartPlcSettings", JSON.stringify(settings));
    this.toast("Settings saved locally.", "success");
  }

  renderNav() {
    this.elements.sidebarNav.innerHTML = navItems.map((item) => `
      <button class="${item.id === this.activeTab ? "active" : ""}" data-tab="${item.id}" title="${item.label}">
        <span class="nav-icon">${item.icon}</span>
        <span class="nav-label">${item.label}</span>
      </button>
    `).join("");
  }

  renderActiveTab() {
    const tab = tabs.find((item) => item.id === this.activeTab) || tabs[0];
    this.elements.tabPanel.innerHTML = tab.render({
      telemetry: this.telemetry,
      incidents: this.incidents,
    });
  }

  renderFlow() {
    renderFlow(this.elements.pipelineContainer, this.workflow.current(), this.incidents.raw());
  }

  renderStatusPill(forcedHealth = null) {
    const health = this.incidents.health();
    const healthy = forcedHealth ?? health.healthy;
    const label = healthy ? `SQLite linked · ${health.table_count} tables` : "Dashboard API offline";
    this.elements.systemStatusPill.innerHTML = `
      <span class="status-light ${healthy ? "green" : "red"}"></span>
      <span>${label}</span>
    `;
  }

  renderIncidentStatus() {
    const incident = this.incidents.latestIncident();
    this.elements.incidentStatusBar.innerHTML = `
      <span class="incident-id">${incident?.correlation_id || "No active incident"}</span>
      <span class="incident-status-badge ${incident ? "active-inc" : ""}">${incident?.status || "IDLE"}</span>
    `;
  }

  renderLauncher() {
    const running = this.incidents.isRunning();
    const button = this.elements.projectLauncherBtn;
    button.className = `launcher-btn ${running ? "running" : "stopped"}`;
    button.querySelector(".launcher-icon").textContent = running ? "■" : "▶";
    button.querySelector(".launcher-text").textContent = running ? "Stop Project Services" : "Open Factory I/O, Then Start Project";
  }

  toast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    this.elements.toastContainer.appendChild(toast);
    window.setTimeout(() => {
      toast.classList.add("removing");
      window.setTimeout(() => toast.remove(), 220);
    }, 4200);
  }

  async refreshLiveViews() {
    await this.refreshSnapshot();
    this.renderFlow();
    if (["monitoring", "analytics", "alerts", "agents", "twin", "simulation"].includes(this.activeTab)) {
      this.renderActiveTab();
    }
  }
}

new DashboardApp().start();
