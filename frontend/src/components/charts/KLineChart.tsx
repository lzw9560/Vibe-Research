// klinecharts v10 K 线图——缩放/拖拽/crosshair + MA + 画线投研工具 + 成交量副图。
// A 股红涨绿跌。dark warm-orange 主题。换掉 pure SVG（无缩放/拖拽/画线库限制）。
import { useEffect, useRef } from "react";
import { init, type Chart, type KLineData } from "klinecharts";

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
  /** 显示 MA 均线（MA5/MA10/MA20），默认 true */
  showMA?: boolean;
  /** K 线维度：4=日K 5=周K 6=月K 11=60min（决定 setPeriod） */
  category?: number;
}

// 画线工具栏（klinecharts 内置 overlay 名）
const DRAW_TOOLS: { name: string; label: string }[] = [
  { name: "segment", label: "趋势线" },
  { name: "horizontalStraightLine", label: "水平线" },
  { name: "verticalStraightLine", label: "垂直线" },
  { name: "parallelStraightLine", label: "平行线" },
  { name: "rectangle", label: "矩形" },
  { name: "triangle", label: "三角" },
  { name: "parallelogram", label: "平行四边" },
  { name: "fibonacciLine", label: "斐波那契" },
  { name: "priceLine", label: "价格线" },
  { name: "simpleAnnotation", label: "文字标注" },
  { name: "simpleTag", label: "标签" },
];

// 转换：项目 Bar → klinecharts KLineData（timestamp ms）
function toKLineData(b: Bar): KLineData {
  // 60min bar 有 timestamp（ms，窗口开始）直接用；日K 只有 date，转当日 00:00 北京时间 → UTC ms
  const ts = (b as any).timestamp ?? new Date(b.date + "T00:00:00+08:00").getTime();
  return {
    timestamp: ts,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
    volume: b.volume,
  };
}

/**
 * klinecharts K 线图。缩放（滚轮 Y）/拖拽（左右滚动历史）/crosshair + OHLCV tooltip +
 * MA5(黄)/MA10(紫)/MA20(白) + 成交量副图 + 画线投研工具栏（趋势线/水平线/矩形/三角/
 * 平行线/斐波那契/价格线/文字标注/标签）。A 股红涨绿跌。
 */
export function KLineChart({ bars, height = 460, showMA = true, category = 4 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = init(containerRef.current, {
      locale: "zh-CN",
      styles: {
        grid: {
          horizontal: { color: "rgba(255,255,255,0.04)" },
          vertical: { color: "rgba(255,255,255,0.04)" },
        },
        candle: {
          type: "candle_solid",
          // A 股红涨绿跌 + 十字星中性灰
          bar: {
            upColor: "#ef4444",
            downColor: "#22c55e",
            noChangeColor: "#9ca3af",
            upBorderColor: "#ef4444",
            downBorderColor: "#22c55e",
            noChangeBorderColor: "#9ca3af",
            upWickColor: "#ef4444",
            downWickColor: "#22c55e",
            noChangeWickColor: "#9ca3af",
          },
          tooltip: {
            showRule: "always",
            rect: { color: "rgba(20,20,23,0.92)", borderColor: "rgba(255,255,255,0.12)" },
          },
          priceMark: {
            high: { color: "#ef4444" },
            low: { color: "#22c55e" },
            last: { upColor: "#ef4444", downColor: "#22c55e", noChangeColor: "#9ca3af" },
          },
        },
        xAxis: {
          axisLine: { color: "rgba(255,255,255,0.15)" },
          tickText: { color: "rgba(255,255,255,0.5)" },
        },
        yAxis: {
          axisLine: { color: "rgba(255,255,255,0.15)" },
          tickText: { color: "rgba(255,255,255,0.5)" },
        },
        crosshair: {
          horizontal: {
            line: { color: "rgba(255,255,255,0.3)" },
            text: { backgroundColor: "#ea580c" }, // 暖橙
          },
          vertical: {
            line: { color: "rgba(255,255,255,0.3)" },
            text: { backgroundColor: "#ea580c" },
          },
        },
      },
    });
    if (!chart) return;
    chartRef.current = chart;
    // eslint-disable-next-line no-console
    console.log("[KLineChart] init ok", { w: containerRef.current?.clientWidth, h: containerRef.current?.clientHeight });

    // v10: setSymbol 在 init（setPeriod 移数据 useEffect 按 category 动态——日/周/月/60min）
    chart.setSymbol({ ticker: "KLINE", pricePrecision: 2, volumePrecision: 0 });

    // 主图叠加 MA + 成交量副图（v10 createIndicator 只接 value+isStack）
    chart.createIndicator("MA", true); // isStack=true 叠加主图
    chart.createIndicator("VOL", false); // 成交量副图（独立 pane）
    if (!showMA) {
      chart.removeIndicator({ name: "MA" }); // 隐藏由 showMA 控制
    }

    return () => {
      chart.resize();
    };
  }, [showMA]);

  // 数据注入：setPeriod（按 category 动态）+ setDataLoader（v10 最后）+ subscribeBar（Required）
  // setPeriod 按 category：日K→day / 周→week / 月→month / 60min→minute:60
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    // setPeriod 按 category（必须在 setDataLoader 前——period 变触发 getBars 重新加载）
    const period = category === 11 ? { type: "minute" as const, span: 60 }
      : category === 5 ? { type: "week" as const, span: 1 }
      : category === 6 ? { type: "month" as const, span: 1 }
      : { type: "day" as const, span: 1 };
    chart.setPeriod(period);
    const kdata = bars.map(toKLineData);
    chart.setDataLoader({
      getBars: ({ callback, type }) => {
        // eslint-disable-next-line no-console
        console.log("[KLineChart] getBars", { type, kdataLen: kdata.length, first: kdata[0] });
        callback(kdata, false);
      },
      subscribeBar: () => { console.log("[KLineChart] subscribeBar called"); },
      unsubscribeBar: () => {},
    });
    // 默认显示最新交易日（滚到最右=最新 bar，用户要"最后一个交易日的 K 线"）
    chart.scrollToRealTime();
  }, [bars]);

  // 监听窗口 resize
  useEffect(() => {
    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  if (!bars.length) {
    return (
      <div className="flex h-[320px] items-center justify-center rounded-md border border-dashed border-border/40 text-sm text-muted-foreground">
        暂无 K 线数据（mootdx intraday 故障 + baostock 无 60min 分时源）
      </div>
    );
  }

  const handleTool = (overlayName: string) => {
    chartRef.current?.createOverlay(overlayName);
  };

  return (
    <div className="space-y-2">
      {/* 画线投研工具栏 */}
      <div className="flex flex-wrap items-center gap-1 border-b border-border/40 pb-1">
        <span className="mr-1 text-[10px] text-muted-foreground">画线</span>
        {DRAW_TOOLS.map((t) => (
          <button
            key={t.name}
            type="button"
            onClick={() => handleTool(t.name)}
            title={t.label}
            className="rounded border border-border/40 bg-muted/10 px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-primary/15 hover:text-primary"
          >
            {t.label}
          </button>
        ))}
      </div>
      {/* K 线主图（klinecharts 挂载点） */}
      <div
        ref={containerRef}
        className="w-full"
        style={{ height: `${height}px` }}
      />
      <p className="text-[10px] text-muted-foreground">
        滚轮缩放 · 左右拖拽滚动 · hover 看十字线 + OHLCV · 点画线工具在图上画（可拖拽端点/删除）
      </p>
    </div>
  );
}

export default KLineChart;
