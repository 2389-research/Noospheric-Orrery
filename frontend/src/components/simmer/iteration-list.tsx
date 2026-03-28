"use client";

import { useState, useEffect, useRef } from "react";
import { SimmerIteration } from "@/lib/types";

interface IterationListProps {
  iterations: SimmerIteration[];
  selectedIndex: number;
  onSelect: (index: number) => void;
  isRunning: boolean;
  isCompleted: boolean;
  onVisibleCountChange?: (count: number | null) => void;
  bestIndex?: number;
}

export function IterationList({
  iterations,
  selectedIndex,
  onSelect,
  isRunning,
  isCompleted,
  onVisibleCountChange,
  bestIndex,
}: IterationListProps) {
  const [replayState, setReplayState] = useState<"idle" | "playing" | "done">("idle");
  const [replaySpeed, setReplaySpeed] = useState(1);
  const [visibleCount, setVisibleCount] = useState(iterations.length);
  const [fadingIn, setFadingIn] = useState<Set<number>>(new Set());
  const replayRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // When iterations grow (running), always show new ones
  useEffect(() => {
    if (replayState === "idle") {
      setVisibleCount(iterations.length);
      onVisibleCountChange?.(null); // null = show all
    }
  }, [iterations.length, replayState]);

  // Report visible count changes during replay
  useEffect(() => {
    if (replayState === "playing") {
      onVisibleCountChange?.(visibleCount);
    } else if (replayState === "done" || replayState === "idle") {
      onVisibleCountChange?.(null);
    }
  }, [visibleCount, replayState]);

  function startReplay() {
    if (replayRef.current) clearTimeout(replayRef.current);
    setVisibleCount(0);
    setFadingIn(new Set());
    setReplayState("playing");

    function revealNext(idx: number) {
      if (idx >= iterations.length) {
        setReplayState("done");
        return;
      }
      setVisibleCount(idx + 1);
      setFadingIn((prev) => new Set(prev).add(idx));
      const gap = 300 / replaySpeed;
      replayRef.current = setTimeout(() => revealNext(idx + 1), gap);
    }

    setTimeout(() => revealNext(0), 100);
  }

  function skipReplay() {
    if (replayRef.current) clearTimeout(replayRef.current);
    setVisibleCount(iterations.length);
    setFadingIn(new Set());
    setReplayState("done");
    onVisibleCountChange?.(null);
  }

  const displayedIterations = iterations.slice(0, visibleCount);

  function getDelta(index: number): number | null {
    if (index === 0) return null;
    return iterations[index].composite - iterations[index - 1].composite;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Replay controls for completed jobs */}
      {isCompleted && (
        <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border/20">
          <button
            onClick={startReplay}
            className="text-[9px] tracking-[1px] text-muted-foreground/90 hover:text-foreground/90 transition-colors px-1.5 py-0.5 border border-border/30 rounded"
          >
            ▶ Replay
          </button>
          {([1, 2, 5] as const).map((speed) => (
            <button
              key={speed}
              onClick={() => setReplaySpeed(speed)}
              className={`text-[9px] px-1 py-0.5 border rounded transition-colors ${
                replaySpeed === speed
                  ? "border-purple-500/50 text-purple-400"
                  : "border-border/20 text-muted-foreground/90 hover:text-muted-foreground/90"
              }`}
            >
              {speed}x
            </button>
          ))}
          <button
            onClick={skipReplay}
            className="text-[9px] tracking-[1px] text-muted-foreground/90 hover:text-muted-foreground/85 transition-colors px-1 py-0.5"
          >
            ⏭ Skip
          </button>
        </div>
      )}

      {/* Iteration rows */}
      <div className="flex-1 overflow-y-auto">
        {displayedIterations.map((iter, idx) => {
          const delta = getDelta(idx);
          const isSelected = idx === selectedIndex;
          const isFading = fadingIn.has(idx);

          return (
            <div
              key={idx}
              onClick={() => onSelect(idx)}
              className={[
                "px-3 py-2.5 border-b border-border/10 cursor-pointer transition-all",
                isSelected
                  ? "border-l-2 border-l-purple-500 bg-purple-500/5"
                  : iter.regressed
                  ? "border-l-2 border-l-red-500/60 hover:bg-card/50"
                  : "border-l-2 border-l-transparent hover:bg-card/50",
                isFading ? "animate-in fade-in duration-500" : "",
              ].join(" ")}
            >
              <div className="flex items-baseline justify-between mb-0.5">
                <span className="text-[9px] tracking-[2px] text-muted-foreground/90 uppercase">
                  iter {iter.iteration}
                  {idx === bestIndex && (
                    <span className="ml-1.5 text-[8px] text-emerald-400 border border-emerald-400/40 px-1 rounded">★ used</span>
                  )}
                </span>
                <div className="flex items-center gap-1">
                  {delta !== null && !iter.regressed && delta > 0 && (
                    <span className="text-[9px] text-emerald-400">+{delta.toFixed(1)}</span>
                  )}
                  {iter.regressed && (
                    <span className="text-[9px] text-red-400 border border-red-400/40 px-1 rounded">↓ reg</span>
                  )}
                  {delta !== null && delta === 0 && !iter.regressed && (
                    <span className="text-[9px] text-muted-foreground/85">—</span>
                  )}
                </div>
              </div>
              <div className="text-base font-semibold text-foreground/90 leading-none mb-1">
                {iter.composite.toFixed(1)}
              </div>
              {iter.key_change && !iter.key_change.match(/^iteration-\d+$/) && (
                <div className="text-[9px] text-muted-foreground/85 truncate leading-tight">
                  {iter.key_change.replace(/^\*+\s*/, "")}
                </div>
              )}
            </div>
          );
        })}

        {/* Pulsing placeholder when running */}
        {isRunning && (
          <div className="px-3 py-2.5 border-b border-border/10 border-l-2 border-l-amber-500/40">
            <div className="text-[9px] tracking-[2px] text-muted-foreground/85 uppercase mb-1">
              iter {iterations.length}
            </div>
            <div className="text-[10px] text-amber-400/60 animate-pulse">
              reasoning...
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
