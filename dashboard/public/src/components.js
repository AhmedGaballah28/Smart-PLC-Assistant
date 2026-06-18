export function gauge(parameter) {
  const percent = ((parameter.value - parameter.min) / (parameter.max - parameter.min)) * 100;
  const clamped = Math.max(0, Math.min(100, percent));
  return `
    <article class="metric-card ${parameter.state}">
      <div class="metric-top">
        <span>${parameter.label}</span>
        <strong>${parameter.value}<small>${parameter.unit}</small></strong>
      </div>
      <div class="gauge-track"><span style="width:${clamped}%"></span></div>
    </article>
  `;
}

export function lineChart(title, values, unit = "") {
  const width = 360;
  const height = 120;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 22) - 11;
    return `${x},${y}`;
  }).join(" ");

  return `
    <article class="chart-card">
      <div class="chart-head">
        <h3>${title}</h3>
        <span>${values.at(-1)} ${unit}</span>
      </div>
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${title} trend chart">
        <polyline class="chart-grid" points="0,95 360,95"></polyline>
        <polyline class="chart-grid" points="0,60 360,60"></polyline>
        <polyline class="chart-line" points="${points}"></polyline>
      </svg>
    </article>
  `;
}

export function confidenceMeter(score) {
  const normalized = score <= 1 ? score * 100 : score;
  const clamped = Math.max(0, Math.min(100, Math.round(normalized)));
  return `
    <div class="confidence" aria-label="Confidence ${clamped}%">
      <span style="width:${clamped}%"></span>
      <strong>${clamped}%</strong>
    </div>
  `;
}

export function table(headers, rows) {
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>
      </table>
    </div>
  `;
}
