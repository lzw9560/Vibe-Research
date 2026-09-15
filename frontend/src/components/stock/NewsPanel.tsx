// 资讯面板——调 /api/news + /api/announcements 渲染个股新闻与公告。
// 右侧 RightPanel「资讯」tab 内容（Phase 2 接线）。两个数据源独立（akshare / 东财），
// 用 Promise.allSettled 独立失败：一方宕仍展示另一方，不互相拖累。
// 诚实状态：loading / error / empty 均如实呈现，不臆造。
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { NewsItem, Announcement } from "@/lib/api";

interface Props {
  /** 当前个股代码 */
  code: string;
}

/** 缩短发布时间：只保留日期+时分（去掉秒/年份前缀冗余），失败原样返回。 */
function shortTime(raw: string | undefined): string | null {
  if (!raw) return null;
  // 形如 "2024-01-15 10:30:00" → "01-15 10:30"；形如 "2024-01-15" → 原样
  const m = raw.match(/^\d{4}-(\d{2}-\d{2})\s+(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : raw;
}

export function NewsPanel({ code }: Props) {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(false);
  const [newsErr, setNewsErr] = useState<string | null>(null);
  const [annErr, setAnnErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNewsErr(null);
    setAnnErr(null);
    Promise.allSettled([api.news(code), api.announcements(code)])
      .then(([newsRes, annRes]) => {
        if (cancelled) return;
        if (newsRes.status === "fulfilled") {
          setNews(Array.isArray(newsRes.value) ? newsRes.value : []);
        } else {
          setNewsErr(
            newsRes.reason instanceof Error
              ? newsRes.reason.message
              : String(newsRes.reason),
          );
        }
        if (annRes.status === "fulfilled") {
          setAnnouncements(
            Array.isArray(annRes.value) ? annRes.value : [],
          );
        } else {
          setAnnErr(
            annRes.reason instanceof Error
              ? annRes.reason.message
              : String(annRes.reason),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  const allEmpty =
    !loading && !newsErr && !annErr && news.length === 0 && announcements.length === 0;

  return (
    <div className="space-y-4">
      {/* 新闻 */}
      <section className="space-y-2">
        <h5 className="text-xs font-semibold text-muted-foreground">
          新闻 <span className="text-primary">{news.length}</span>
        </h5>

        {loading && (
          <p className="text-xs text-muted-foreground">加载新闻…</p>
        )}
        {newsErr && (
          <p className="text-xs text-danger">新闻加载失败：{newsErr}</p>
        )}
        {!loading && !newsErr && news.length === 0 && !allEmpty && (
          <p className="text-xs text-muted-foreground">暂无新闻</p>
        )}

        <div className="space-y-2">
          {news.map((n, i) => {
            const title = n["新闻标题"] || "无标题";
            const source = n["文章来源"];
            const time = shortTime(n["发布时间"]);
            const link = n["新闻链接"];
            const titleNode = (
              <span className="text-sm leading-snug text-foreground hover:text-primary">
                {title}
              </span>
            );
            return (
              <div
                key={`news-${i}`}
                className="space-y-1.5 rounded-lg border border-border/60 bg-muted/10 p-3"
              >
                {link ? (
                  <a
                    href={link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block"
                  >
                    {titleNode}
                  </a>
                ) : (
                  <div>{titleNode}</div>
                )}
                {(source || time) && (
                  <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                    {source && <span>{source}</span>}
                    {time && <span>· {time}</span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* 公告 */}
      <section className="space-y-2">
        <h5 className="text-xs font-semibold text-muted-foreground">
          公告 <span className="text-primary">{announcements.length}</span>
        </h5>

        {loading && (
          <p className="text-xs text-muted-foreground">加载公告…</p>
        )}
        {annErr && (
          <p className="text-xs text-danger">公告加载失败：{annErr}</p>
        )}
        {!loading && !annErr && announcements.length === 0 && !allEmpty && (
          <p className="text-xs text-muted-foreground">暂无公告</p>
        )}

        <div className="space-y-2">
          {announcements.map((a, i) => (
            <div
              key={`ann-${i}`}
              className="space-y-1.5 rounded-lg border border-border/60 bg-muted/10 p-3"
            >
              {a.url ? (
                <a
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block"
                >
                  <span className="text-sm leading-snug text-foreground hover:text-primary">
                    {a.title || "无标题"}
                  </span>
                </a>
              ) : (
                <div className="text-sm leading-snug text-foreground">
                  {a.title || "无标题"}
                </div>
              )}
              <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                {a.type && (
                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                    {a.type}
                  </span>
                )}
                {a.date && <span>{a.date}</span>}
              </div>
            </div>
          ))}
        </div>
      </section>

      {allEmpty && (
        <p className="py-4 text-center text-xs text-muted-foreground">
          该股暂无资讯
        </p>
      )}
    </div>
  );
}

export default NewsPanel;
