"use client";

import { useEffect, useRef } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Line } from "react-chartjs-2";
import { SimmerIteration } from "@/lib/types";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

const COMPOSITE_COLOR = "#7F77DD";
const CRITERION_COLORS = ["#378ADD", "#BA7517", "#1D9E75", "#9B5E8A", "#6B7280"];

interface TrajectoryChartProps {
  iterations: SimmerIteration[];
  selectedIndex: number;
}

export function TrajectoryChart({ iterations, selectedIndex }: TrajectoryChartProps) {
  if (iterations.length === 0) return null;

  // Collect all criterion names
  const criterionNames = Array.from(
    new Set(
      iterations.flatMap((iter) => Object.keys(iter.scores))
    )
  );

  const labels = iterations.map((iter) => `i${iter.iteration}`);

  const compositeData = iterations.map((iter) => iter.composite);

  const criterionDatasets = criterionNames.map((name, ci) => ({
    label: name,
    data: iterations.map((iter) => iter.scores[name] ?? null),
    borderColor: CRITERION_COLORS[ci % CRITERION_COLORS.length],
    backgroundColor: "transparent",
    borderDash: [4, 3],
    borderWidth: 1.5,
    spanGaps: true,
    pointRadius: iterations.map((_, idx) => (idx === selectedIndex ? 5 : 2)),
    pointBackgroundColor: iterations.map((_, idx) =>
      idx === selectedIndex
        ? CRITERION_COLORS[ci % CRITERION_COLORS.length]
        : CRITERION_COLORS[ci % CRITERION_COLORS.length]
    ),
    pointBorderColor: iterations.map((_, idx) =>
      idx === selectedIndex ? "#ffffff" : "transparent"
    ),
    pointBorderWidth: iterations.map((_, idx) => (idx === selectedIndex ? 2 : 0)),
    tension: 0.3,
  }));

  const compositeDataset = {
    label: "composite",
    data: compositeData,
    borderColor: COMPOSITE_COLOR,
    backgroundColor: "transparent",
    borderWidth: 3,
    borderDash: [] as number[],
    pointRadius: iterations.map((_, idx) => (idx === selectedIndex ? 6 : 3)),
    pointBackgroundColor: iterations.map((_, idx) =>
      idx === selectedIndex ? COMPOSITE_COLOR : COMPOSITE_COLOR
    ),
    pointBorderColor: iterations.map((_, idx) =>
      idx === selectedIndex ? "#ffffff" : "transparent"
    ),
    pointBorderWidth: iterations.map((_, idx) => (idx === selectedIndex ? 2 : 0)),
    tension: 0.3,
  };

  const data = {
    labels,
    datasets: [compositeDataset, ...criterionDatasets],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: {
        display: true,
        position: "bottom" as const,
        labels: {
          color: "rgba(255,255,255,0.4)",
          font: { size: 9, family: "monospace" },
          boxWidth: 12,
          padding: 8,
          usePointStyle: true,
          pointStyleWidth: 8,
        },
      },
      tooltip: {
        backgroundColor: "rgba(20,20,20,0.9)",
        titleColor: "rgba(255,255,255,0.7)",
        bodyColor: "rgba(255,255,255,0.5)",
        titleFont: { size: 10, family: "monospace" },
        bodyFont: { size: 9, family: "monospace" },
        padding: 8,
        borderColor: "rgba(255,255,255,0.1)",
        borderWidth: 1,
      },
    },
    scales: {
      x: {
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: { color: "rgba(255,255,255,0.3)", font: { size: 9 } },
      },
      y: {
        // Auto-scale with padding — scores are 0-10 but cluster in a range
        min: Math.max(0, Math.floor(Math.min(...compositeData, ...criterionNames.flatMap(n => iterations.map(i => i.scores[n] ?? 10))) - 1)),
        max: Math.min(10, Math.ceil(Math.max(...compositeData, ...criterionNames.flatMap(n => iterations.map(i => i.scores[n] ?? 0))) + 1)),
        grid: { color: "rgba(255,255,255,0.05)" },
        ticks: {
          color: "rgba(255,255,255,0.3)",
          font: { size: 9 },
          stepSize: 1,
        },
      },
    },
  };

  return (
    <div style={{ height: "200px" }}>
      <Line data={data} options={options} />
    </div>
  );
}
