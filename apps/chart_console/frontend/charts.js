export function toTs(v) {
  return Math.floor(new Date(v).getTime() / 1000);
}

export function initCharts(ids) {
  const common = {
    layout: { background: { color: "#101831" }, textColor: "#d6ddf5" },
    grid: { vertLines: { color: "#25325a" }, horzLines: { color: "#25325a" } },
  };
  const mainChart = LightweightCharts.createChart(document.getElementById(ids.main), common);
  const macdChart = LightweightCharts.createChart(document.getElementById(ids.macd), common);
  const rsiChart = LightweightCharts.createChart(document.getElementById(ids.rsi), common);
  const secondChart = LightweightCharts.createChart(document.getElementById(ids.second), common);

  const series = {
    candle: mainChart.addCandlestickSeries(),
    vol: mainChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" }),
    draw: mainChart.addLineSeries({ color: "#ff9aa2", lineWidth: 2 }),
    macdHist: macdChart.addHistogramSeries(),
    macdDif: macdChart.addLineSeries({ color: "#f4d35e" }),
    macdDea: macdChart.addLineSeries({ color: "#9ad1ff" }),
    rsi: rsiChart.addLineSeries({ color: "#a7f3d0" }),
    second: secondChart.addLineSeries({ color: "#c8b6ff", lineWidth: 2 }),
    ma: [],
  };

  function syncCrosshair(source, target) {
    source.subscribeCrosshairMove((param) => {
      if (!param || !param.time) return;
      target.setCrosshairPosition(param.point?.x ?? 0, param.point?.y ?? 0, target);
    });
  }
  mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (!range) return;
    secondChart.timeScale().setVisibleLogicalRange(range);
  });
  syncCrosshair(mainChart, secondChart);

  return { mainChart, macdChart, rsiChart, secondChart, series };
}

export function renderDraw(series, drawObjects) {
  const pts = [];
  for (const d of drawObjects || []) {
    if (d.type === "line" && d.x0 && d.x1) {
      pts.push({ time: toTs(d.x0), value: Number(d.y0 || 0) });
      pts.push({ time: toTs(d.x1), value: Number(d.y1 || d.y0 || 0) });
    } else if (d.type === "hline" && d.x0) {
      pts.push({ time: toTs(d.x0), value: Number(d.y0 || 0) });
    }
  }
  series.draw.setData(pts);
}

/** K 线日历日（本地时区），用于对齐 screening run_date */
export function barDayKey(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 在蜡烛图 series 上标记「选股日」（与某根 K 线时间对齐）。 */
export function applyScreeningDayMarker(candleSeries, bars, dateStr) {
  if (!candleSeries || typeof candleSeries.setMarkers !== "function") return;
  if (!dateStr || !bars?.length) {
    candleSeries.setMarkers([]);
    return;
  }
  const day = String(dateStr).slice(0, 10);
  const hit = bars.filter((b) => barDayKey(b.time) === day);
  let t;
  if (hit.length) {
    t = hit[hit.length - 1].time;
  } else {
    const want = new Date(`${day}T12:00:00`).getTime() / 1000;
    t = bars.reduce((best, b) => (Math.abs(b.time - want) < Math.abs(best.time - want) ? b : best)).time;
  }
  candleSeries.setMarkers([
    {
      time: t,
      position: "belowBar",
      color: "#f4d35e",
      shape: "circle",
      text: "选股日",
    },
  ]);
}
