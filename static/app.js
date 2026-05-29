const growthPctEl = document.getElementById('growth-pct');
const greenCoverageEl = document.getElementById('green-coverage');
const baselineCoverageEl = document.getElementById('baseline-coverage');
const greenPixelsEl = document.getElementById('green-pixels');
const roiAreaEl = document.getElementById('roi-area');
const greenBlobsEl = document.getElementById('green-blobs');
const largestBlobAreaEl = document.getElementById('largest-blob-area');
const timestampEl = document.getElementById('timestamp');
const roiReadyEl = document.getElementById('roi-ready');
const baselineReadyEl = document.getElementById('baseline-ready');
const frameSizeEl = document.getElementById('frame-size');
const sourceModeEl = document.getElementById('source-mode');
const errorBoxEl = document.getElementById('error-box');
const historySaveMinutesEl = document.getElementById('history-save-minutes');
const historyCurrentWindowPeakEl = document.getElementById('history-current-window-peak');
const historyLastPeakGrowthEl = document.getElementById('history-last-peak-growth');
const historyLastSavedAtEl = document.getElementById('history-last-saved-at');

const btnUndo = document.getElementById('btn-undo');
const btnClear = document.getElementById('btn-clear');
const btnSaveRoi = document.getElementById('btn-save-roi');
const btnResetBaseline = document.getElementById('btn-reset-baseline');
const btnRefreshRoiFrame = document.getElementById('btn-refresh-roi-frame');
const pointCountEl = document.getElementById('point-count');
const roiSaveStatusEl = document.getElementById('roi-save-status');
const canvas = document.getElementById('roi-canvas');
const ctx = canvas.getContext('2d');

const historyChartCanvas = document.getElementById('history-chart');
const historyChartCtx = historyChartCanvas.getContext('2d');
const historyEmptyStateEl = document.getElementById('history-empty-state');
const historyPointCountEl = document.getElementById('history-point-count');
const historyWindowRangeEl = document.getElementById('history-window-range');
const chartLastSavedGrowthEl = document.getElementById('chart-last-saved-growth');
const chartLastSavedCoverageEl = document.getElementById('chart-last-saved-coverage');
const chartCurrentWindowGrowthEl = document.getElementById('chart-current-window-growth');
const chartCurrentWindowCoverageEl = document.getElementById('chart-current-window-coverage');

let currentImage = new Image();
let currentPoints = [];
let existingPoints = [];
let frameLoaded = false;
let latestHistoryPayload = null;

function setCanvasSizeToImage(img) {
  canvas.width = img.width;
  canvas.height = img.height;
}

function drawPolygon(points, strokeStyle, fillStyle) {
  if (!points || points.length === 0) return;
  ctx.save();
  ctx.lineWidth = 2;
  ctx.strokeStyle = strokeStyle;
  ctx.fillStyle = fillStyle;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
  if (points.length >= 3) { ctx.closePath(); ctx.fill(); }
  ctx.stroke();
  points.forEach((p, idx) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = strokeStyle;
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.font = '12px sans-serif';
    ctx.fillText(String(idx), p.x + 6, p.y - 6);
  });
  ctx.restore();
}

function drawCanvas() {
  if (!frameLoaded) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(currentImage, 0, 0, canvas.width, canvas.height);
  if (existingPoints.length >= 3) drawPolygon(existingPoints, 'rgba(0, 180, 255, 1)', 'rgba(0, 180, 255, 0.12)');
  if (currentPoints.length > 0) drawPolygon(currentPoints, 'rgba(255, 180, 0, 1)', 'rgba(255, 180, 0, 0.15)');
  pointCountEl.textContent = String(currentPoints.length);
}

async function loadCurrentFrame() {
  const cacheBust = `t=${Date.now()}`;
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      currentImage = img;
      setCanvasSizeToImage(img);
      frameLoaded = true;
      drawCanvas();
      resolve();
    };
    img.onerror = reject;
    img.src = `/api/current_frame.jpg?${cacheBust}`;
  });
}

async function fetchStatus() {
  try {
    const response = await fetch('/api/status');
    const data = await response.json();
    growthPctEl.textContent = `${Number(data.growth_pct || 0).toFixed(2)}%`;
    greenCoverageEl.textContent = `${Number(data.green_coverage_pct || 0).toFixed(2)}%`;
    baselineCoverageEl.textContent = `${Number(data.baseline_green_pct || 0).toFixed(2)}%`;
    greenPixelsEl.textContent = String(data.green_pixels || 0);
    roiAreaEl.textContent = String(data.roi_area_px || 0);
    greenBlobsEl.textContent = String(data.green_blobs || 0);
    largestBlobAreaEl.textContent = Number(data.largest_blob_area || 0).toFixed(2);
    timestampEl.textContent = data.timestamp || '--';
    roiReadyEl.textContent = data.roi_ready ? 'Sí' : 'No';
    baselineReadyEl.textContent = data.baseline_ready ? 'Sí' : 'No';
    frameSizeEl.textContent = `${data.frame_width || '--'} x ${data.frame_height || '--'}`;
    sourceModeEl.textContent = data.source_mode || '--';
    historySaveMinutesEl.textContent = `${Number(data.history_save_minutes || 0)} min`;
    historyCurrentWindowPeakEl.textContent = `${Number(data.history_current_window_peak_growth_pct || 0).toFixed(2)}%`;
    historyLastPeakGrowthEl.textContent = `${Number(data.history_last_peak_growth_pct || 0).toFixed(2)}%`;
    historyLastSavedAtEl.textContent = data.history_last_saved_at || '--';
    if (data.error) {
      errorBoxEl.textContent = data.error;
      errorBoxEl.classList.add('error');
    } else {
      errorBoxEl.textContent = 'Sin errores';
      errorBoxEl.classList.remove('error');
    }
  } catch (err) {
    errorBoxEl.textContent = `Error consultando estado: ${err}`;
    errorBoxEl.classList.add('error');
  }
}

async function fetchExistingRoi() {
  try {
    const response = await fetch('/api/roi');
    const data = await response.json();
    existingPoints = (data.points || []).map(p => ({ x: Number(p.x), y: Number(p.y) }));
    drawCanvas();
  } catch (err) {
    roiSaveStatusEl.textContent = `No se pudo cargar ROI actual: ${err}`;
  }
}

async function saveRoi() {
  if (currentPoints.length < 3) {
    roiSaveStatusEl.textContent = 'Debes marcar al menos 3 puntos';
    return;
  }
  try {
    const response = await fetch('/api/roi', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: currentPoints })
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'Error guardando ROI');
    existingPoints = [...currentPoints];
    currentPoints = [];
    drawCanvas();
    roiSaveStatusEl.textContent = `ROI guardado. Baseline recalibrado en ${Number(data.baseline_green_pct || 0).toFixed(2)}%`;
    await fetchStatus();
    await fetchHistory();
  } catch (err) {
    roiSaveStatusEl.textContent = `Error guardando ROI: ${err.message || err}`;
  }
}

async function resetBaseline() {
  try {
    const response = await fetch('/api/baseline/reset', { method: 'POST' });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || 'No se pudo recalibrar baseline');
    roiSaveStatusEl.textContent = `Baseline recalibrado: ${Number(data.baseline_green_pct || 0).toFixed(2)}%`;
    await fetchStatus();
    await fetchHistory();
  } catch (err) {
    roiSaveStatusEl.textContent = `Error recalibrando baseline: ${err.message || err}`;
  }
}

function setupHiDPICanvas(canvasEl, desiredHeight = 320) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = Math.max(320, canvasEl.parentElement.clientWidth);
  const cssHeight = desiredHeight;
  canvasEl.style.width = `${cssWidth}px`;
  canvasEl.style.height = `${cssHeight}px`;
  canvasEl.width = Math.floor(cssWidth * dpr);
  canvasEl.height = Math.floor(cssHeight * dpr);
  const localCtx = canvasEl.getContext('2d');
  localCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { width: cssWidth, height: cssHeight };
}

function formatPct(value) {
  return `${Number(value || 0).toFixed(2)}%`;
}

function drawHistoryChart(payload) {
  latestHistoryPayload = payload;
  const { width, height } = setupHiDPICanvas(historyChartCanvas, 320);
  const c = historyChartCtx;
  c.clearRect(0, 0, width, height);

  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  const latestSaved = payload?.latest_saved || null;
  const currentWindow = payload?.current_window || null;

  historyPointCountEl.textContent = String(rows.length);
  chartLastSavedGrowthEl.textContent = formatPct(latestSaved?.peak_growth_pct || 0);
  chartLastSavedCoverageEl.textContent = formatPct(latestSaved?.peak_green_coverage_pct || 0);
  chartCurrentWindowGrowthEl.textContent = formatPct(currentWindow?.peak_growth_pct || 0);
  chartCurrentWindowCoverageEl.textContent = formatPct(currentWindow?.peak_green_coverage_pct || 0);

  if (currentWindow?.bucket_start && currentWindow?.bucket_end) {
    historyWindowRangeEl.textContent = `${currentWindow.bucket_start} → ${currentWindow.bucket_end}`;
  } else {
    historyWindowRangeEl.textContent = '--';
  }

  if (!rows.length) {
    historyEmptyStateEl.style.display = 'block';
    c.fillStyle = 'rgba(148, 163, 184, 0.8)';
    c.font = '14px sans-serif';
    c.fillText('Sin datos históricos todavía', 24, 36);
    return;
  }

  historyEmptyStateEl.style.display = 'none';

  const pad = { left: 58, right: 18, top: 20, bottom: 42 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const yMax = Math.max(1, Number(payload?.y_max || 1));
  const minX = 0;
  const maxX = Math.max(rows.length - 1, 1);

  const growthValues = rows.map(r => Number(r.peak_growth_pct || 0));
  const coverageValues = rows.map(r => Number(r.peak_green_coverage_pct || 0));

  function xPos(index) {
    return pad.left + (index - minX) / (maxX - minX || 1) * chartW;
  }
  function yPos(value) {
    return pad.top + chartH - (Math.max(0, value) / yMax) * chartH;
  }

  c.save();
  c.strokeStyle = 'rgba(255,255,255,0.08)';
  c.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (chartH / 4) * i;
    c.beginPath();
    c.moveTo(pad.left, y);
    c.lineTo(width - pad.right, y);
    c.stroke();

    const labelValue = ((4 - i) / 4) * yMax;
    c.fillStyle = 'rgba(148,163,184,0.85)';
    c.font = '12px sans-serif';
    c.fillText(`${labelValue.toFixed(1)}%`, 8, y + 4);
  }

  for (let i = 0; i < rows.length; i++) {
    const x = xPos(i);
    c.beginPath();
    c.moveTo(x, pad.top);
    c.lineTo(x, pad.top + chartH);
    c.strokeStyle = i === rows.length - 1 ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.03)';
    c.stroke();
  }

  c.strokeStyle = 'rgba(255,255,255,0.18)';
  c.beginPath();
  c.moveTo(pad.left, pad.top + chartH);
  c.lineTo(width - pad.right, pad.top + chartH);
  c.stroke();

  function drawSeries(values, stroke, fill, pointFill) {
    if (!values.length) return;
    c.beginPath();
    values.forEach((v, i) => {
      const x = xPos(i);
      const y = yPos(v);
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    });
    c.strokeStyle = stroke;
    c.lineWidth = 2.5;
    c.stroke();

    c.lineTo(xPos(values.length - 1), pad.top + chartH);
    c.lineTo(xPos(0), pad.top + chartH);
    c.closePath();
    c.fillStyle = fill;
    c.fill();

    values.forEach((v, i) => {
      const x = xPos(i);
      const y = yPos(v);
      c.beginPath();
      c.arc(x, y, 3, 0, Math.PI * 2);
      c.fillStyle = pointFill;
      c.fill();
    });
  }

  drawSeries(coverageValues, 'rgba(56, 189, 248, 0.95)', 'rgba(56, 189, 248, 0.08)', 'rgba(125, 211, 252, 1)');
  drawSeries(growthValues, 'rgba(34, 197, 94, 0.98)', 'rgba(34, 197, 94, 0.14)', 'rgba(134, 239, 172, 1)');

  const maxLabels = 6;
  const step = Math.max(1, Math.ceil(rows.length / maxLabels));
  c.fillStyle = 'rgba(148,163,184,0.9)';
  c.font = '12px sans-serif';
  rows.forEach((row, index) => {
    if (index % step !== 0 && index !== rows.length - 1) return;
    const x = xPos(index);
    const rawLabel = row.bucket_start || row.peak_timestamp || '';
    const label = rawLabel.length >= 16 ? rawLabel.slice(5, 16) : rawLabel;
    c.save();
    c.translate(x, height - 12);
    c.rotate(-0.35);
    c.fillText(label, 0, 0);
    c.restore();
  });

  const latestIndex = rows.length - 1;
  const latestGrowth = growthValues[latestIndex];
  const latestCoverage = coverageValues[latestIndex];
  c.fillStyle = 'rgba(240,248,255,0.95)';
  c.font = '12px sans-serif';
  c.fillText(`Último crecimiento: ${latestGrowth.toFixed(2)}%`, pad.left + 10, pad.top + 16);
  c.fillText(`Última cobertura: ${latestCoverage.toFixed(2)}%`, pad.left + 10, pad.top + 34);
  c.restore();
}

async function fetchHistory() {
  try {
    const response = await fetch('/api/history?limit=240');
    const payload = await response.json();
    drawHistoryChart(payload);
  } catch (err) {
    historyEmptyStateEl.style.display = 'block';
    historyEmptyStateEl.textContent = `No se pudo cargar el histórico: ${err}`;
  }
}

canvas.addEventListener('click', (event) => {
  if (!frameLoaded) return;
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const x = Math.round((event.clientX - rect.left) * scaleX);
  const y = Math.round((event.clientY - rect.top) * scaleY);
  currentPoints.push({ x, y });
  drawCanvas();
});

btnUndo.addEventListener('click', () => {
  if (currentPoints.length) {
    currentPoints.pop();
    drawCanvas();
  }
});
btnClear.addEventListener('click', () => {
  currentPoints = [];
  drawCanvas();
});
btnSaveRoi.addEventListener('click', saveRoi);
btnResetBaseline.addEventListener('click', resetBaseline);
btnRefreshRoiFrame.addEventListener('click', async () => {
  await loadCurrentFrame();
  await fetchExistingRoi();
  roiSaveStatusEl.textContent = 'Frame actualizado para edición de ROI';
});

window.addEventListener('resize', () => {
  if (latestHistoryPayload) drawHistoryChart(latestHistoryPayload);
});

async function bootstrap() {
  await loadCurrentFrame();
  await fetchExistingRoi();
  await fetchStatus();
  await fetchHistory();
  setInterval(fetchStatus, 1000);
  setInterval(fetchHistory, 5000);
}

bootstrap();
