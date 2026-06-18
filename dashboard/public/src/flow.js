import { agentNodes } from "./data.js";

export function renderFlow(container, activeNodeId, snapshot = {}) {
  const activeIndex = Math.max(0, agentNodes.findIndex((node) => node.id === activeNodeId));
  const eventByStage = new Map();

  for (const event of snapshot.events || []) {
    const stage = String(event.stage || "").toLowerCase();
    const mapped = stage === "diagnostic" ? "diagnose" : stage === "validation" ? "validate" : stage;
    if (!eventByStage.has(mapped)) eventByStage.set(mapped, event);
  }

  container.innerHTML = agentNodes.map((node, index) => {
    const event = eventByStage.get(node.id);
    const completed = index < activeIndex ? "completed" : "";
    const active = node.id === activeNodeId ? "active" : "";
    const humanGate = node.kind === "human-gate" ? "human-gate" : "";
    const stamp = event?.created_at ? new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "waiting";
    const arrow = index < agentNodes.length - 1 ? `<span class="pipeline-arrow">→</span>` : "";

    return `
      <article class="pipeline-step ${completed} ${active} ${humanGate}" data-node="${node.id}">
        <span class="step-label">${node.label}</span>
        <span class="step-meta">${stamp}</span>
      </article>
      ${arrow}
    `;
  }).join("");
}
