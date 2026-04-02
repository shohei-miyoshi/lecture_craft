import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../utils/constants.js";

function cardStyle(accent) {
  return {
    padding: 16,
    borderRadius: 14,
    background: "linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.00))",
    border: `1px solid ${accent}`,
    boxShadow: "0 14px 30px rgba(0,0,0,.18)",
  };
}

function num(value) {
  return Number(value ?? 0).toLocaleString("ja-JP");
}

function timeText(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("ja-JP", { hour12: false });
  } catch {
    return String(value);
  }
}

function MetricCard({ title, value, hint, accent, tone }) {
  return (
    <div style={cardStyle(accent)}>
      <div style={{ fontSize: 10, letterSpacing: "1.6px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>{title}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <div style={{ fontFamily: "var(--ff)", fontSize: 30, lineHeight: 1, color: tone }}>{num(value)}</div>
        <div style={{ fontSize: 11, color: "var(--ts)" }}>{hint}</div>
      </div>
    </div>
  );
}

function BreakdownList({ title, items, color }) {
  const total = items.reduce((sum, item) => sum + Number(item.count ?? 0), 0) || 1;
  return (
    <div style={{ padding: 14, borderRadius: 12, background: "var(--s2)", border: "1px solid var(--bd)" }}>
      <div style={{ fontFamily: "var(--ff)", fontSize: 12, marginBottom: 10 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.length === 0 ? (
          <div style={{ fontSize: 11, color: "var(--tm)" }}>まだデータがありません</div>
        ) : (
          items.map((item) => {
            const count = Number(item.count ?? 0);
            return (
              <div key={item.label}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--ts)", marginBottom: 4 }}>
                  <span>{item.label}</span>
                  <span style={{ fontFamily: "var(--fm)", color: "var(--tp)" }}>{num(count)}</span>
                </div>
                <div style={{ height: 6, borderRadius: 999, background: "var(--s4)", overflow: "hidden" }}>
                  <div style={{ width: `${Math.max(6, (count / total) * 100)}%`, height: "100%", background: color }} />
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function TableSection({ title, rows, columns, emptyText }) {
  return (
    <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
      <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>{title}</div>
      {rows.length === 0 ? (
        <div style={{ fontSize: 11, color: "var(--tm)" }}>{emptyText}</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col.key} style={{ textAlign: "left", padding: "0 0 8px", color: "var(--tm)", fontWeight: 600, borderBottom: "1px solid var(--bd)" }}>
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={row.id ?? row.job_id ?? row.run_id ?? row.snapshot_path ?? rowIndex}>
                  {columns.map((col) => (
                    <td key={col.key} style={{ padding: "10px 0", borderBottom: "1px solid rgba(255,255,255,.04)", color: "var(--ts)", verticalAlign: "top" }}>
                      <span style={{ color: col.emphasis ? "var(--tp)" : "inherit", fontFamily: col.mono ? "var(--fm)" : "inherit" }}>
                        {col.render ? col.render(row) : String(row[col.key] ?? "—")}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function AdminDashboard({ addToast }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/admin/overview?limit=12`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const next = await res.json();
      setData(next);
    } catch (err) {
      setError(err.message || "failed");
      if (!silent) addToast?.("er", "管理ダッシュボードの取得に失敗しました");
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(() => load({ silent: true }), 20000);
    return () => clearInterval(timer);
  }, []);

  const jobsByMode = useMemo(() => data?.breakdowns?.jobs_by_mode ?? [], [data]);
  const jobsByStatus = useMemo(() => data?.breakdowns?.jobs_by_status ?? [], [data]);
  const exportsByType = useMemo(() => data?.breakdowns?.exports_by_type ?? [], [data]);
  const researchByTrigger = useMemo(() => data?.breakdowns?.research_by_trigger ?? [], [data]);

  return (
    <div style={{ height: "100%", overflow: "auto", background: "radial-gradient(circle at top left, rgba(91,141,239,.14), transparent 34%), radial-gradient(circle at top right, rgba(76,175,130,.12), transparent 28%), var(--bg)" }}>
      <div style={{ maxWidth: 1320, margin: "0 auto", padding: "22px 22px 40px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 18 }}>
          <div>
            <div style={{ fontFamily: "var(--ff)", fontSize: 26, lineHeight: 1.05, marginBottom: 8 }}>Admin Dashboard</div>
            <div style={{ color: "var(--ts)", fontSize: 12, lineHeight: 1.6 }}>
              実験 run の状況、生成ジョブの利用量、export の利用状況をここでまとめて確認できます。
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 10, color: "var(--tm)" }}>更新: {timeText(data?.generated_at)}</div>
            <button onClick={() => load()} style={{ padding: "7px 10px", border: "1px solid var(--bd2)", borderRadius: 10, background: "var(--s2)", color: "var(--tp)", fontSize: 11 }}>
              再読み込み
            </button>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: 30, borderRadius: 16, background: "var(--s2)", border: "1px solid var(--bd)", color: "var(--ts)" }}>読み込み中...</div>
        ) : error ? (
          <div style={{ padding: 30, borderRadius: 16, background: "var(--rdd)", border: "1px solid rgba(224,91,91,.35)", color: "var(--rd)" }}>
            管理データの取得に失敗しました: {error}
          </div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 12, marginBottom: 18 }}>
              <MetricCard title="Generate Jobs" value={data?.usage?.jobs_total} hint="累計ジョブ数" accent="rgba(91,141,239,.24)" tone="var(--ac)" />
              <MetricCard title="Last 7 Days" value={data?.usage?.jobs_last_7d} hint="直近7日" accent="rgba(76,175,130,.24)" tone="var(--gr)" />
              <MetricCard title="Exports" value={data?.usage?.exports_total} hint="累計書き出し" accent="rgba(232,169,75,.24)" tone="var(--am)" />
              <MetricCard title="Research Sessions" value={data?.research?.total_sessions} hint="研究ログ保存数" accent="rgba(167,139,250,.24)" tone="var(--pu)" />
              <MetricCard title="Experiments" value={data?.experiments?.total_runs} hint="検出された run" accent="rgba(167,139,250,.24)" tone="var(--pu)" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr 1fr", gap: 12, marginBottom: 18 }}>
              <BreakdownList title="Jobs by Mode" items={jobsByMode} color="linear-gradient(90deg, #5b8def, #77a4ff)" />
              <BreakdownList title="Jobs by Status" items={jobsByStatus} color="linear-gradient(90deg, #4caf82, #79d7aa)" />
              <BreakdownList title="Exports by Type" items={exportsByType} color="linear-gradient(90deg, #e8a94b, #ffd28a)" />
              <BreakdownList title="Research by Trigger" items={researchByTrigger} color="linear-gradient(90deg, #a78bfa, #d1c1ff)" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr", gap: 12, marginBottom: 18 }}>
              <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
                <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>Usage Snapshot</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
                  {[
                    ["completed_jobs", "完了ジョブ", "var(--gr)"],
                    ["failed_jobs", "失敗ジョブ", "var(--rd)"],
                    ["cache_hits", "キャッシュヒット", "var(--ac)"],
                    ["deduplicated_jobs", "重複吸収", "var(--am)"],
                    ["jobs_last_24h", "直近24時間", "var(--tp)"],
                    ["exports_last_7d", "直近7日 export", "var(--pu)"],
                  ].map(([key, label, tone]) => (
                    <div key={key} style={{ padding: 12, borderRadius: 12, background: "var(--sur)", border: "1px solid var(--bd)" }}>
                      <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>{label}</div>
                      <div style={{ fontFamily: "var(--fm)", fontSize: 20, color: tone }}>{num(data?.usage?.[key])}</div>
                    </div>
                  ))}
                </div>
              </section>

              <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
                <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>Research Snapshot</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                  {[
                    ["highlights_modified", "HL修正", "var(--am)"],
                    ["highlights_accepted", "HL許容", "var(--gr)"],
                    ["sentences_text_modified", "台本文修正", "var(--ac)"],
                    ["sentences_timing_modified", "台本時間修正", "var(--pu)"],
                    ["sentences_added", "台本追加", "var(--tp)"],
                    ["sentences_removed", "台本削除", "var(--rd)"],
                  ].map(([key, label, tone]) => (
                    <div key={key} style={{ padding: 12, borderRadius: 12, background: "var(--sur)", border: "1px solid var(--bd)" }}>
                      <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>{label}</div>
                      <div style={{ fontFamily: "var(--fm)", fontSize: 20, color: tone }}>
                        {num(data?.research?.summary_totals?.[key])}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
                <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>Experiment Snapshot</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div style={{ padding: 12, borderRadius: 12, background: "var(--sur)", border: "1px solid var(--bd)" }}>
                    <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>完走 run</div>
                    <div style={{ fontFamily: "var(--fm)", fontSize: 22, color: "var(--gr)" }}>{num(data?.experiments?.completed_runs)}</div>
                  </div>
                  <div style={{ padding: 12, borderRadius: 12, background: "var(--sur)", border: "1px solid var(--bd)" }}>
                    <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>失敗 run</div>
                    <div style={{ fontFamily: "var(--fm)", fontSize: 22, color: "var(--rd)" }}>{num(data?.experiments?.failed_runs)}</div>
                  </div>
                </div>
              </section>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 12, marginBottom: 18 }}>
              <TableSection
                title="Recent Generate Jobs"
                rows={data?.recent_jobs ?? []}
                emptyText="まだジョブ履歴はありません"
                columns={[
                  { key: "job_id", label: "Job ID", mono: true, emphasis: true },
                  { key: "status", label: "Status", emphasis: true },
                  { key: "payload", label: "Mode", render: (row) => row.payload?.mode ?? "—" },
                  { key: "message", label: "Message" },
                  { key: "updated_at", label: "Updated", render: (row) => timeText(row.updated_at) },
                ]}
              />
              <TableSection
                title="Recent Exports"
                rows={data?.recent_exports ?? []}
                emptyText="まだ export 履歴はありません"
                columns={[
                  { key: "export_type", label: "Type", emphasis: true },
                  { key: "status", label: "Status" },
                  { key: "mode", label: "Mode" },
                  { key: "sentence_count", label: "Sentences", mono: true },
                  { key: "created_at", label: "Created", render: (row) => timeText(row.created_at) },
                ]}
              />
            </div>

            <TableSection
              title="Recent Research Sessions"
              rows={data?.research?.recent_sessions ?? []}
              emptyText="研究セッションの保存履歴はまだありません"
              columns={[
                { key: "session_id", label: "Session", mono: true, emphasis: true },
                { key: "trigger", label: "Trigger", emphasis: true },
                { key: "mode", label: "Mode" },
                { key: "research", label: "HL修正", mono: true, render: (row) => row.research?.summary?.highlights_modified ?? "0" },
                { key: "research", label: "台本文修正", mono: true, render: (row) => row.research?.summary?.sentences_text_modified ?? "0" },
                { key: "saved_at", label: "Saved", render: (row) => timeText(row.saved_at) },
              ]}
            />

            <TableSection
              title="Recent Experiment Runs"
              rows={data?.experiments?.recent_runs ?? []}
              emptyText="experiments/runs に run がまだありません"
              columns={[
                { key: "run_id", label: "Run ID", mono: true, emphasis: true },
                { key: "completed", label: "Done", render: (row) => row.completed ? "YES" : "NO" },
                { key: "all_ok", label: "All OK", render: (row) => row.all_ok ? "YES" : "NO" },
                { key: "failure_count", label: "Failures", mono: true },
                { key: "step_count", label: "Steps", mono: true },
                { key: "updated_at", label: "Updated", render: (row) => timeText(row.updated_at) },
              ]}
            />
          </>
        )}
      </div>
    </div>
  );
}
