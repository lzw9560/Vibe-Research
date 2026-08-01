import { useRef, useState, useMemo } from "react";

interface Bar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

interface Props {
  bars: Bar[];
  height?: number;
}

/**
 * Pure SVG K-line (candlestick) chart.
 * Red (#ef4444) = up (close >= open), Green (#22c55e) = down.
 * Volume bars below, crosshair on hover showing OHLCV.
 */
export function KLineChart({ bars, height: propHeight = 420 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const H = propHeight;
  const W = 100; // viewBox percentage coordinate system

const MAIN_H = H * 0.72;
const VOL_H = H * 0.18;
const GAP = H * 0.04;
const PADDING_TOP = 10;

  const n = bars.length;
  if (!n) {
    return (
      <div
        className="flex h-[320px] items-center justify-center text-sm text-muted-foreground"
      >
        暂无K线数据
      </div>
    );
  }

  // Auto-scale price range
  const allHigh = Math.max(...bars.map((b) => b.high));
  const allLow = Math.min(...bars.map((b) => b.low));
  const pricePad = (allHigh - allLow) * 0.05 || 1;
  const priceMin = allLow - pricePad;
  const priceMax = allHigh + pricePad;
  const priceRange = priceMax - priceMin || 1;

  // Volume scale
  const maxVol = Math.max(...bars.map((b) => b.volume), 1);

  // Map helpers
  const priceToY = (p: number) =>
    PADDING_TOP + (1 - (p - priceMin) / priceRange) * (MAIN_H - PADDING_TOP);
  const volToH = (v: number) => (v / maxVol) * VOL_H;
  const idxToX = (i: number) => (i / (n - 1 || 1)) * (W - 4) + 2;
  const candleW = Math.max(1, Math.min(8, (W - 4) / n * 0.6));

  // Crosshair data
  const hover = hoverIdx != null ? bars[hoverIdx] : null;

  // Date labels: show every Nth label
  const labelStep = n <= 10 ? 1 : n <= 30 ? 5 : n <= 100 ? 10 : 20;
  const dateLabels = useMemo(
    () =>
      Array.from({ length: n }, (_, i) =>
        i % labelStep === 0 || i === n - 1
          ? { date: bars[i].date, x: idxToX(i) }
          : null
      ).filter(Boolean) as { date: string; x: number }[],
    [n, bars, labelStep, idxToX]
  );

  // Determine if candle is up or down
  const isUp = (b: Bar) => b.close >= b.open;

  // Grid lines
  const gridLines = useMemo(() => {
    const lines: { y: number; label: string }[] = [];
    const steps = 5;
    for (let i = 0; i <= steps; i++) {
      const price = priceMin + (priceRange * i) / steps;
      lines.push({
        y: priceToY(price),
        label: price.toFixed(2),
      });
    }
    return lines;
  }, [priceMin, priceRange, priceToY]);

  return (
    <div className="w-full overflow-x-auto">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="h-[320px] w-full"
        onMouseMove={(e) => {
          if (!svgRef.current || !n) return;
          const rect = svgRef.current.getBoundingClientRect();
          const xPct = ((e.clientX - rect.left) / rect.width) * 100;
          const idx = Math.round(((xPct - 2) / (W - 4)) * (n - 1));
          const clamped = Math.max(0, Math.min(n - 1, idx));
          setHoverIdx(clamped);
        }}
        onMouseLeave={() => {
          setHoverIdx(null);
        }}
      >
        {/* Background */}
        <rect x="0" y="0" width={W} height={H} fill="transparent" />

        {/* Price grid lines */}
        {gridLines.map((g, i) => (
          <g key={i}>
            <line
              x1="2"
              x2={W - 2}
              y1={g.y}
              y2={g.y}
              stroke="currentColor"
              strokeOpacity="0.08"
              strokeDasharray="2 2"
            />
            <text
              x={W - 2}
              y={g.y - 2}
              textAnchor="end"
              fontSize="5"
              fill="currentColor"
              opacity="0.5"
            >
              {g.label}
            </text>
          </g>
        ))}

        {/* Candles */}
        {bars.map((b, i) => {
          const x = idxToX(i);
          const up = isUp(b);
          const color = up ? "#ef4444" : "#22c55e";
          const bodyTop = priceToY(Math.max(b.open, b.close));
          const bodyBot = priceToY(Math.min(b.open, b.close));
          const bodyH = Math.max(1, bodyBot - bodyTop);
          const wickTop = priceToY(b.high);
          const wickBot = priceToY(b.low);

          return (
            <g key={i}>
              {/* Wick */}
              <line
                x1={x}
                x2={x}
                y1={wickTop}
                y2={wickBot}
                stroke={color}
                strokeWidth="0.8"
              />
              {/* Body */}
              <rect
                x={x - candleW / 2}
                y={bodyTop}
                width={candleW}
                height={bodyH}
                fill={up ? color : color}
                stroke={color}
                strokeWidth="0.3"
                rx="0.3"
                opacity={hoverIdx === i ? 1 : 0.85}
              />
              {/* Volume bar */}
              <rect
                x={x - candleW / 2}
                y={MAIN_H + GAP + VOL_H - volToH(b.volume)}
                width={candleW}
                height={volToH(b.volume)}
                fill={color}
                opacity={0.4}
                rx="0.2"
              />
            </g>
          );
        })}

        {/* Crosshair */}
        {hoverIdx != null && (
          <g>
            {/* Vertical line */}
            <line
              x1={idxToX(hoverIdx)}
              x2={idxToX(hoverIdx)}
              y1="0"
              y2={H}
              stroke="currentColor"
              strokeOpacity="0.25"
              strokeDasharray="3 2"
            />
            {/* Highlight candle */}
            {(() => {
              const b = bars[hoverIdx];
              const x = idxToX(hoverIdx);
              const up = isUp(b);
              const color = up ? "#ef4444" : "#22c55e";
              const bodyTop = priceToY(Math.max(b.open, b.close));
              const bodyBot = priceToY(Math.min(b.open, b.close));
              const bodyH = Math.max(1, bodyBot - bodyTop);
              const wickTop = priceToY(b.high);
              const wickBot = priceToY(b.low);
              return (
                <g>
                  <line x1={x} x2={x} y1={wickTop} y2={wickBot} stroke={color} strokeWidth="1.2" />
                  <rect
                    x={x - candleW / 2}
                    y={bodyTop}
                    width={candleW}
                    height={bodyH}
                    fill={color}
                    stroke={color}
                    strokeWidth="0.5"
                    rx="0.3"
                  />
                </g>
              );
            })()}
          </g>
        )}

        {/* Date labels */}
        {dateLabels.map((dl, i) => (
          <text
            key={i}
            x={dl.x}
            y={MAIN_H + GAP + VOL_H + 10}
            textAnchor="middle"
            fontSize="4.5"
            fill="currentColor"
            opacity="0.5"
          >
            {dl.date}
          </text>
        ))}

        {/* Separator lines */}
        <line
          x1="2"
          x2={W - 2}
          y1={MAIN_H}
          y2={MAIN_H}
          stroke="currentColor"
          strokeOpacity="0.15"
        />
        <line
          x1="2"
          x2={W - 2}
          y1={MAIN_H + GAP}
          y2={MAIN_H + GAP}
          stroke="currentColor"
          strokeOpacity="0.15"
        />

        {/* Volume label */}
        <text
          x="4"
          y={MAIN_H + GAP + 6}
          fontSize="4"
          fill="currentColor"
          opacity="0.4"
        >
          成交量
        </text>
      </svg>

      {/* Hover tooltip */}
      {hover && hoverIdx != null && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/40 px-3 py-2 text-xs font-mono">
          <span className="text-muted-foreground">{hover.date}</span>
          <span>O <span className={`${isUp(hover) ? "text-danger" : "text-success"} ml-0.5`}>{hover.open}</span></span>
          <span>H <span className="ml-0.5">{hover.high}</span></span>
          <span>L <span className="ml-0.5">{hover.low}</span></span>
          <span>C <span className={`${isUp(hover) ? "text-danger" : "text-success"} ml-0.5`}>{hover.close}</span></span>
          <span className="text-muted-foreground">
            Vol {(hover.volume / 1e4).toFixed(0)}万
          </span>
        </div>
      )}
    </div>
  );
}
