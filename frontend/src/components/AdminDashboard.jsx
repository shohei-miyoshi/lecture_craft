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

function MetricCard({ title, value, hint, accent, tone, suffix = "" }) {
  return (
    <div style={cardStyle(accent)}>
      <div style={{ fontSize: 10, letterSpacing: "1.6px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>{title}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <div style={{ fontFamily: "var(--ff)", fontSize: 30, lineHeight: 1, color: tone }}>
          {num(value)}{suffix}
        </div>
        <div style={{ fontSize: 11, color: "var(--ts)" }}>{hint}</div>
      </div>
    </div>
  );
}

function BreakdownList({ title, items, color, emptyText = "まだデータがありません" }) {
  const total = items.reduce((sum, item) => sum + Number(item.count ?? 0), 0) || 1;
  return (
    <div style={{ padding: 14, borderRadius: 12, background: "var(--s2)", border: "1px solid var(--bd)" }}>
      <div style={{ fontFamily: "var(--ff)", fontSize: 12, marginBottom: 10 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.length === 0 ? (
          <div style={{ fontSize: 11, color: "var(--tm)" }}>{emptyText}</div>
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

function ActivityChart({ rows }) {
  const maxTotal = Math.max(1, ...(rows ?? []).map((row) => Number(row.total ?? 0)));
  return (
    <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
      <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>直近14日の利用推移</div>
      {rows?.length ? (
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))`, gap: 8, alignItems: "end", minHeight: 180 }}>
          {rows.map((row) => (
            <div key={row.date} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
              <div style={{ width: "100%", height: 120, display: "flex", alignItems: "end", justifyContent: "center" }}>
                <div style={{ width: "100%", maxWidth: 26, height: `${Math.max(8, (Number(row.total ?? 0) / maxTotal) * 100)}%`, borderRadius: "10px 10px 4px 4px", background: "linear-gradient(180deg, rgba(91,141,239,.95), rgba(110,193,255,.55))", boxShadow: "inset 0 1px 0 rgba(255,255,255,.15)" }} />
              </div>
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--tp)" }}>{num(row.total)}</div>
              <div style={{ fontSize: 10, color: "var(--tm)" }}>{row.label}</div>
              <div style={{ fontSize: 9, color: "var(--tm)", textAlign: "center", lineHeight: 1.45 }}>
                G {num(row.jobs)} / E {num(row.exports)} / R {num(row.research)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 11, color: "var(--tm)" }}>まだ利用データがありません</div>
      )}
    </section>
  );
}

function TopSlides({ rows }) {
  return (
    <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
      <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>よく編集されたスライド</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows?.length ? rows.map((row) => (
          <div key={row.label} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "10px 12px", borderRadius: 12, background: "var(--sur)", border: "1px solid var(--bd)" }}>
            <span style={{ color: "var(--tp)" }}>{row.label}</span>
            <span style={{ fontFamily: "var(--fm)", color: "var(--ac)" }}>{num(row.count)}</span>
          </div>
        )) : (
          <div style={{ fontSize: 11, color: "var(--tm)" }}>まだ十分な編集ログがありません</div>
        )}
      </div>
    </section>
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
                <tr key={row.id ?? row.job_id ?? row.session_id ?? row.snapshot_path ?? rowIndex}>
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
  const exportsByType = useMemo(() => data?.breakdowns?.exports_by_type ?? [], [data]);
  const researchByTrigger = useMemo(() => data?.breakdowns?.research_by_trigger ?? [], [data]);
  const operationTypes = useMemo(() => data?.breakdowns?.operation_types ?? [], [data]);
  const sentenceFieldChanges = useMemo(() => data?.breakdowns?.sentence_change_fields ?? [], [data]);
  const highlightFieldChanges = useMemo(() => data?.breakdowns?.highlight_change_fields ?? [], [data]);
  const dailyActivity = useMemo(() => data?.activity?.last_14_days ?? [], [data]);
  const topSlides = useMemo(() => data?.research?.analytics?.top_slide_activity ?? [], [data]);

  return (
    <div style={{ height: "100%", overflow: "auto", background: "radial-gradient(circle at top left, rgba(91,141,239,.14), transparent 34%), radial-gradient(circle at top right, rgba(76,175,130,.12), transparent 28%), var(--bg)" }}>
      <div style={{ maxWidth: 1320, margin: "0 auto", padding: "22px 22px 40px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 18 }}>
          <div>
            <div style={{ fontFamily: "var(--ff)", fontSize: 26, lineHeight: 1.05, marginBottom: 8 }}>管理ダッシュボード</div>
            <div style={{ color: "var(--ts)", fontSize: 12, lineHeight: 1.6 }}>
              Web アプリ上の生成・編集・書き出し履歴を集計して、研究で見たい傾向をまとめて確認できます。
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 12, marginBottom: 18 }}>
              <MetricCard title="生成ジョブ" value={data?.usage?.jobs_total} hint="累計ジョブ数" accent="rgba(91,141,239,.24)" tone="var(--ac)" />
              <MetricCard title="直近7日" value={data?.usage?.jobs_last_7d} hint="生成数" accent="rgba(76,175,130,.24)" tone="var(--gr)" />
              <MetricCard title="書き出し" value={data?.usage?.exports_total} hint="累計書き出し" accent="rgba(232,169,75,.24)" tone="var(--am)" />
              <MetricCard title="研究セッション" value={data?.research?.total_sessions} hint="保存済みセッション" accent="rgba(167,139,250,.24)" tone="var(--pu)" />
              <MetricCard title="ユニーク教材" value={data?.usage?.unique_materials} hint="生成参照の教材数" accent="rgba(127,224,208,.24)" tone="var(--tp)" />
              <MetricCard title="平均作業時間" value={data?.research?.analytics?.avg_active_minutes_per_session} hint="1セッションあたり" accent="rgba(110,193,255,.24)" tone="var(--ac)" suffix="分" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12, marginBottom: 18 }}>
              <BreakdownList title="モード別ジョブ数" items={jobsByMode} color="linear-gradient(90deg, #5b8def, #77a4ff)" />
              <BreakdownList title="書き出し種別" items={exportsByType} color="linear-gradient(90deg, #e8a94b, #ffd28a)" />
              <BreakdownList title="研究トリガ" items={researchByTrigger} color="linear-gradient(90deg, #a78bfa, #d1c1ff)" />
              <BreakdownList title="操作種別" items={operationTypes.slice(0, 8)} color="linear-gradient(90deg, #6ec1ff, #9fd7ff)" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr", gap: 12, marginBottom: 18 }}>
              <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
                <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>利用状況スナップショット</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
                  {[
                    ["completed_jobs", "完了ジョブ", "var(--gr)"],
                    ["failed_jobs", "失敗ジョブ", "var(--rd)"],
                    ["exports_last_7d", "直近7日 export", "var(--am)"],
                    ["operation_logs_total", "総操作ログ", "var(--tp)"],
                    ["study_events_total", "総研究イベント", "var(--pu)"],
                    ["unique_generation_keys", "生成キー数", "var(--ac)"],
                  ].map(([key, label, tone]) => (
                    <div key={key} style={{ padding: 12, borderRadius: 12, background: "var(--sur)", border: "1px solid var(--bd)" }}>
                      <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>{label}</div>
                      <div style={{ fontFamily: "var(--fm)", fontSize: 20, color: tone }}>{num(data?.usage?.[key])}</div>
                    </div>
                  ))}
                </div>
              </section>

              <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
                <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>研究ログ集計</div>
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
                      <div style={{ fontFamily: "var(--fm)", fontSize: 20, color: tone }}>{num(data?.research?.summary_totals?.[key])}</div>
                    </div>
                  ))}
                </div>
              </section>

              <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)" }}>
                <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 10 }}>編集セッション傾向</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {[
                    ["平均操作ログ数", data?.research?.analytics?.avg_operation_logs_per_session, "件"],
                    ["平均研究イベント数", data?.research?.analytics?.avg_study_events_per_session, "件"],
                    ["台本編集あり", data?.research?.analytics?.sessions_with_sentence_edits, "セッション"],
                    ["HL編集あり", data?.research?.analytics?.sessions_with_highlight_edits, "セッション"],
                    ["書き出し到達", data?.research?.analytics?.sessions_with_exports, "セッション"],
                  ].map(([label, value, suffix]) => (
                    <div key={label} style={{ padding: 12, borderRadius: 12, background: "var(--sur)", border: "1px solid var(--bd)", display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <div style={{ fontSize: 10, color: "var(--tm)" }}>{label}</div>
                      <div style={{ fontFamily: "var(--fm)", color: "var(--tp)" }}>{num(value)}{suffix}</div>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.4fr .8fr .8fr", gap: 12, marginBottom: 18 }}>
              <ActivityChart rows={dailyActivity} />
              <BreakdownList title="台本文の変更項目" items={sentenceFieldChanges} color="linear-gradient(90deg, #5b8def, #9fd7ff)" emptyText="台本文変更はまだありません" />
              <BreakdownList title="HLの変更項目" items={highlightFieldChanges} color="linear-gradient(90deg, #e8a94b, #ffd28a)" emptyText="HL変更はまだありません" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
              <TopSlides rows={topSlides} />
              <BreakdownList title="研究モード別" items={data?.breakdowns?.research_by_mode ?? []} color="linear-gradient(90deg, #7fe0d0, #b0f0e5)" emptyText="研究モードの記録はまだありません" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 12, marginBottom: 18 }}>
              <TableSection
                title="最近の研究セッション"
                rows={data?.research?.recent_sessions ?? []}
                emptyText="研究セッションの保存履歴はまだありません"
                columns={[
                  { key: "session_id", label: "セッションID", mono: true, emphasis: true },
                  { key: "trigger", label: "トリガ", emphasis: true },
                  { key: "mode", label: "モード" },
                  { key: "metrics", label: "操作数", mono: true, render: (row) => row.metrics?.operation_log_count ?? "0" },
                  { key: "metrics", label: "作業時間", mono: true, render: (row) => `${row.metrics?.active_minutes ?? 0}分` },
                  { key: "metrics", label: "HL編集", mono: true, render: (row) => row.metrics?.highlight_edit_count ?? "0" },
                  { key: "metrics", label: "台本編集", mono: true, render: (row) => row.metrics?.sentence_edit_count ?? "0" },
                  { key: "saved_at", label: "保存時刻", render: (row) => timeText(row.saved_at) },
                ]}
              />
              <TableSection
                title="最近の書き出し"
                rows={data?.recent_exports ?? []}
                emptyText="まだ export 履歴はありません"
                columns={[
                  { key: "export_type", label: "種別", emphasis: true },
                  { key: "status", label: "状態" },
                  { key: "mode", label: "モード" },
                  { key: "sentence_count", label: "台本文数", mono: true },
                  { key: "highlight_count", label: "枠数", mono: true },
                  { key: "created_at", label: "作成時刻", render: (row) => timeText(row.created_at) },
                ]}
              />
            </div>

            <TableSection
              title="最近の生成ジョブ"
              rows={data?.recent_jobs ?? []}
              emptyText="まだジョブ履歴はありません"
              columns={[
                { key: "job_id", label: "ジョブID", mono: true, emphasis: true },
                { key: "status", label: "状態", emphasis: true },
                { key: "payload", label: "モード", render: (row) => row.payload?.mode ?? "—" },
                { key: "progress", label: "進捗", mono: true, render: (row) => `${row.progress ?? 0}%` },
                { key: "message", label: "メッセージ" },
                { key: "updated_at", label: "更新時刻", render: (row) => timeText(row.updated_at) },
              ]}
            />
          </>
        )}
      </div>
    </div>
  );
}
