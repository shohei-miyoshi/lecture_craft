import { useEffect, useMemo, useState } from "react";
import { authFetch } from "../utils/sessionStore.js";

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

function bytesText(value) {
  const bytes = Number(value ?? 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
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
                  <div style={{ width: count <= 0 ? "0%" : `${Math.max(6, (count / total) * 100)}%`, height: "100%", background: color }} />
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
  const [runCatalog, setRunCatalog] = useState({ items: [] });
  const [artifactCatalog, setArtifactCatalog] = useState({ items: [], storage: null });
  const [reviewSettings, setReviewSettings] = useState(null);
  const [conditionSettings, setConditionSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [conditionBusy, setConditionBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [scopeType, setScopeType] = useState("global");
  const [scopeKey, setScopeKey] = useState("");
  const [layoutMode, setLayoutMode] = useState("off");
  const [scriptMode, setScriptMode] = useState("off");
  const [kgMode, setKgMode] = useState("off");
  const [logReuseEnabled, setLogReuseEnabled] = useState(false);
  const [reviewFlowEnabled, setReviewFlowEnabled] = useState(true);
  const [promptStrategyVersion, setPromptStrategyVersion] = useState("baseline_v1");

  const load = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    if (!silent) setError("");
    try {
      const [overviewRes, settingsRes, conditionRes, runsRes, artifactsRes] = await Promise.all([
        authFetch(`/api/admin/overview?limit=12`, { method: "GET" }),
        authFetch("/api/admin/review-settings", { method: "GET" }),
        authFetch("/api/admin/experiment-conditions", { method: "GET" }),
        authFetch("/api/admin/runs?limit=100", { method: "GET" }),
        authFetch("/api/admin/artifacts?limit=100", { method: "GET" }),
      ]);
      if (!overviewRes.ok) throw new Error(`HTTP ${overviewRes.status}`);
      if (!settingsRes.ok) throw new Error(`HTTP ${settingsRes.status}`);
      if (!conditionRes.ok) throw new Error(`HTTP ${conditionRes.status}`);
      if (!runsRes.ok) throw new Error(`HTTP ${runsRes.status}`);
      if (!artifactsRes.ok) throw new Error(`HTTP ${artifactsRes.status}`);
      const [next, settings, conditions, runs, artifacts] = await Promise.all([
        overviewRes.json(),
        settingsRes.json(),
        conditionRes.json(),
        runsRes.json(),
        artifactsRes.json(),
      ]);
      setData(next);
      setRunCatalog(runs);
      setArtifactCatalog(artifacts);
      setReviewSettings(settings);
      setConditionSettings(conditions);
      setLayoutMode(settings?.global?.layout_review_mode ?? "off");
      setScriptMode(settings?.global?.script_review_mode ?? "off");
      setKgMode(conditions?.global?.kg_mode ?? "off");
      setLogReuseEnabled(Boolean(conditions?.global?.log_reuse_enabled));
      setReviewFlowEnabled(conditions?.global?.review_flow_enabled !== false);
      setPromptStrategyVersion(conditions?.global?.prompt_strategy_version ?? "baseline_v1");
      setError("");
    } catch (err) {
      if (!silent) {
        setError(err.message || "failed");
        addToast?.("er", "管理ダッシュボードの取得に失敗しました");
      }
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(() => load({ silent: true }), 20000);
    return () => clearInterval(timer);
  }, []);

  const saveReviewSettings = async () => {
    setSettingsBusy(true);
    try {
      const payload = {
        scope_type: scopeType,
        scope_key: scopeType === "experiment" ? scopeKey.trim() || null : null,
        layout_review_mode: layoutMode,
        script_review_mode: scriptMode,
      };
      const res = await authFetch("/api/admin/review-settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load({ silent: true });
      addToast?.("ok", "確認ステップ設定を更新しました");
    } catch (err) {
      addToast?.("er", err.message || "設定更新に失敗しました");
    } finally {
      setSettingsBusy(false);
    }
  };

  const saveExperimentConditions = async () => {
    setConditionBusy(true);
    try {
      const payload = {
        scope_type: scopeType,
        scope_key: scopeType === "experiment" ? scopeKey.trim() || null : null,
        generation_conditions: {
          kg_mode: kgMode,
          log_reuse_enabled: logReuseEnabled,
          review_flow_enabled: reviewFlowEnabled,
          prompt_strategy_version: promptStrategyVersion.trim() || "baseline_v1",
        },
      };
      const res = await authFetch("/api/admin/experiment-conditions", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load({ silent: true });
      addToast?.("ok", "実験生成条件を更新しました");
    } catch (err) {
      addToast?.("er", err.message || "実験生成条件の更新に失敗しました");
    } finally {
      setConditionBusy(false);
    }
  };

  const exportResearchJsonl = async () => {
    setExportBusy(true);
    try {
      const res = await authFetch("/api/research/export-jsonl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          included_only: true,
          include_raw_text: true,
          purpose: "analysis",
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      if (payload.download_url) {
        const fileRes = await authFetch(payload.download_url, { method: "GET" });
        if (!fileRes.ok) throw new Error(`HTTP ${fileRes.status}`);
        const link = document.createElement("a");
        link.href = URL.createObjectURL(await fileRes.blob());
        link.download = `${payload.export_id ?? "lecturecraft-research"}.jsonl`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      }
      addToast?.("ok", `includedに設定したrunの匿名JSONLを書き出しました（${payload.row_count ?? 0}件）`);
    } catch (err) {
      addToast?.("er", err.message || "匿名JSONLの書き出しに失敗しました");
    } finally {
      setExportBusy(false);
    }
  };

  const updateRunStatus = async (runId, analysisStatus) => {
    try {
      const res = await authFetch(`/api/admin/runs/${runId}/analysis-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ analysis_status: analysisStatus }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRunCatalog((current) => ({
        ...current,
        items: current.items.map((row) => (
          row.id === runId ? { ...row, analysis_status: analysisStatus } : row
        )),
      }));
      addToast?.("ok", "実験データの採否を更新しました");
    } catch (err) {
      addToast?.("er", err.message || "実験データの採否を更新できませんでした");
    }
  };

  const jobsByMode = useMemo(() => data?.breakdowns?.jobs_by_mode ?? [], [data]);
  const exportsByType = useMemo(() => data?.breakdowns?.exports_by_type ?? [], [data]);
  const researchByTrigger = useMemo(() => data?.breakdowns?.research_by_trigger ?? [], [data]);
  const operationTypes = useMemo(() => data?.breakdowns?.operation_types ?? [], [data]);
  const sentenceFieldChanges = useMemo(() => data?.breakdowns?.sentence_change_fields ?? [], [data]);
  const highlightFieldChanges = useMemo(() => data?.breakdowns?.highlight_change_fields ?? [], [data]);
  const dailyActivity = useMemo(() => data?.activity?.last_14_days ?? [], [data]);
  const topSlides = useMemo(() => data?.research?.analytics?.top_slide_activity ?? [], [data]);
  const hasUnsupportedReviewMode = layoutMode === "ai" || layoutMode === "ai_then_human";

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
            <button onClick={exportResearchJsonl} disabled={exportBusy} style={{ padding: "7px 10px", border: "1px solid rgba(76,175,130,.35)", borderRadius: 10, background: "rgba(76,175,130,.12)", color: "var(--gr)", fontSize: 11, opacity: exportBusy ? 0.7 : 1 }}>
              {exportBusy ? "出力中..." : "匿名JSONL出力"}
            </button>
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
            <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)", marginBottom: 18 }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 12 }}>
                <div>
                  <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 6 }}>生成フロー設定</div>
                  <div style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.6 }}>
                    LP 後の領域確認ステップと、台本生成後の確認ステップを管理者画面から切り替えられます。
                  </div>
                </div>
                <div style={{ fontSize: 10, color: "var(--tm)" }}>
                  現在の全体設定: 領域 {reviewSettings?.global?.layout_review_mode ?? "off"} / 台本 {reviewSettings?.global?.script_review_mode ?? "off"}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, alignItems: "end", marginBottom: 14 }}>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 10, color: "var(--tm)" }}>対象</span>
                  <select value={scopeType} onChange={(e) => setScopeType(e.target.value)} style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}>
                    <option value="global">全体デフォルト</option>
                    <option value="experiment">実験単位</option>
                  </select>
                </label>

                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 10, color: "var(--tm)" }}>領域確認ステップ</span>
                  <select value={layoutMode} onChange={(e) => setLayoutMode(e.target.value)} style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}>
                    <option value="off">off</option>
                    <option value="human">human</option>
                    <option value="ai" disabled>ai（未実装）</option>
                    <option value="ai_then_human" disabled>ai_then_human（未実装）</option>
                  </select>
                </label>

                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 10, color: "var(--tm)" }}>台本確認ステップ</span>
                  <select value={scriptMode} onChange={(e) => setScriptMode(e.target.value)} style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}>
                    <option value="off">off</option>
                    <option value="human">human</option>
                  </select>
                </label>

                <button onClick={saveReviewSettings} disabled={settingsBusy || hasUnsupportedReviewMode || (scopeType === "experiment" && !scopeKey.trim())} style={{ padding: "9px 14px", border: "1px solid rgba(130,178,255,.4)", background: "var(--ac)", color: "#fff", fontSize: 11, borderRadius: 10, opacity: settingsBusy || hasUnsupportedReviewMode ? 0.7 : 1 }}>
                  {settingsBusy ? "保存中..." : "設定を保存"}
                </button>
              </div>

              {hasUnsupportedReviewMode ? (
                <div style={{ marginBottom: 12, padding: "9px 11px", borderRadius: 10, background: "var(--amd)", border: "1px solid rgba(232,169,75,.3)", color: "var(--am)", fontSize: 11, lineHeight: 1.6 }}>
                  AI 確認モードはまだ未実装です。現在は off または human を選択してください。
                </div>
              ) : null}

              <div style={{ padding: 12, borderRadius: 12, background: "rgba(76,175,130,.06)", border: "1px solid rgba(76,175,130,.18)", marginBottom: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
                  <div>
                    <div style={{ fontFamily: "var(--ff)", fontSize: 12, marginBottom: 4 }}>実験生成条件</div>
                    <div style={{ fontSize: 10, color: "var(--ts)", lineHeight: 1.6 }}>
                      KG利用パターンと修正ログ反映を実験条件として固定します。生成時はバックエンドがこの条件を正として使います。
                    </div>
                  </div>
                  <div style={{ fontSize: 10, color: "var(--tm)", textAlign: "right" }}>
                    全体: KG {conditionSettings?.global?.kg_mode ?? "off"} / ログ {conditionSettings?.global?.log_reuse_enabled ? "ON" : "OFF"}
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, alignItems: "end" }}>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 10, color: "var(--tm)" }}>KGモード</span>
                    <select value={kgMode} onChange={(e) => setKgMode(e.target.value)} style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}>
                      <option value="off">KGなし</option>
                      <option value="slide">スライドKG</option>
                      <option value="global">全体KG</option>
                      <option value="global_slide">全体+スライドKG</option>
                    </select>
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 10, color: "var(--tm)" }}>修正ログ反映</span>
                    <select value={logReuseEnabled ? "on" : "off"} onChange={(e) => setLogReuseEnabled(e.target.value === "on")} style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}>
                      <option value="off">OFF</option>
                      <option value="on">ON</option>
                    </select>
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 10, color: "var(--tm)" }}>確認フロー</span>
                    <select value={reviewFlowEnabled ? "on" : "off"} onChange={(e) => setReviewFlowEnabled(e.target.value === "on")} style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}>
                      <option value="on">ON</option>
                      <option value="off">OFF</option>
                    </select>
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    <span style={{ fontSize: 10, color: "var(--tm)" }}>Prompt strategy</span>
                    <input value={promptStrategyVersion} onChange={(e) => setPromptStrategyVersion(e.target.value)} style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }} />
                  </label>
                  <button onClick={saveExperimentConditions} disabled={conditionBusy || (scopeType === "experiment" && !scopeKey.trim())} style={{ padding: "9px 14px", border: "1px solid rgba(76,175,130,.4)", background: "var(--gr)", color: "#07140f", fontSize: 11, borderRadius: 10, opacity: conditionBusy ? 0.7 : 1 }}>
                    {conditionBusy ? "保存中..." : "生成条件を保存"}
                  </button>
                </div>
              </div>

              {scopeType === "experiment" && (
                <label style={{ display: "grid", gap: 6, marginBottom: 12, maxWidth: 320 }}>
                  <span style={{ fontSize: 10, color: "var(--tm)" }}>実験ID</span>
                  <input
                    value={scopeKey}
                    onChange={(e) => setScopeKey(e.target.value)}
                    placeholder="experiment_xxx"
                    style={{ padding: "9px 10px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}
                  />
                </label>
              )}

              {(reviewSettings?.experiments?.length ?? 0) > 0 && (
                <div style={{ display: "grid", gap: 8 }}>
                  <div style={{ fontSize: 10, color: "var(--tm)" }}>実験単位の上書き設定</div>
                  {reviewSettings.experiments.map((row) => {
                    const conditionRow = (conditionSettings?.experiments ?? []).find((item) => item.experiment_id === row.experiment_id);
                    return (
                    <div key={row.experiment_id} style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto auto", gap: 10, padding: "10px 12px", background: "var(--sur)", border: "1px solid var(--bd)" }}>
                      <div style={{ fontFamily: "var(--fm)", color: "var(--tp)" }}>{row.experiment_id}</div>
                      <div style={{ fontSize: 11, color: "var(--ts)" }}>領域 {row.layout_review_mode}</div>
                      <div style={{ fontSize: 11, color: "var(--ts)" }}>台本 {row.script_review_mode}</div>
                      <div style={{ fontSize: 11, color: "var(--ts)" }}>KG {conditionRow?.kg_mode ?? "off"}</div>
                      <div style={{ fontSize: 11, color: "var(--ts)" }}>ログ {conditionRow?.log_reuse_enabled ? "ON" : "OFF"}</div>
                    </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)", marginBottom: 18 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 12 }}>
                <div>
                  <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 5 }}>生成runと実験データ採否</div>
                  <div style={{ fontSize: 11, color: "var(--ts)" }}>
                    利用者，プロジェクト，実験IDを確認し，研究で使う生成だけをincludedにします．通常利用はgeneralとして区別されます．
                  </div>
                </div>
                <div style={{ fontSize: 10, color: "var(--tm)" }}>{runCatalog.items.length} runs</div>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                  <thead>
                    <tr>
                      {["run ID", "利用者", "プロジェクト", "実験", "用途", "状態", "生成日時", "実験データ"].map((label) => (
                        <th key={label} style={{ textAlign: "left", padding: "0 8px 8px 0", color: "var(--tm)", borderBottom: "1px solid var(--bd)" }}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {runCatalog.items.map((row) => (
                      <tr key={row.id}>
                        <td style={{ padding: "9px 8px 9px 0", fontFamily: "var(--fm)", color: "var(--tp)" }}>{row.id}</td>
                        <td style={{ padding: "9px 8px 9px 0", fontFamily: "var(--fm)" }}>{row.user_id ?? "—"}</td>
                        <td style={{ padding: "9px 8px 9px 0" }}>{row.project_name ?? row.project_id ?? "—"}</td>
                        <td style={{ padding: "9px 8px 9px 0", fontFamily: "var(--fm)" }}>{row.experiment_id ?? "—"}</td>
                        <td style={{ padding: "9px 8px 9px 0" }}>{row.usage_context}</td>
                        <td style={{ padding: "9px 8px 9px 0" }}>{row.status}</td>
                        <td style={{ padding: "9px 8px 9px 0" }}>{timeText(row.created_at)}</td>
                        <td style={{ padding: "9px 0" }}>
                          <select
                            value={row.analysis_status}
                            onChange={(event) => updateRunStatus(row.id, event.target.value)}
                            disabled={row.usage_context !== "research"}
                            style={{ padding: "6px 8px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}
                          >
                            <option value="candidate">candidate</option>
                            <option value="included">included</option>
                            <option value="excluded">excluded</option>
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section style={{ padding: 16, borderRadius: 14, background: "var(--s2)", border: "1px solid var(--bd)", marginBottom: 18 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 12 }}>
                <div>
                  <div style={{ fontFamily: "var(--ff)", fontSize: 13, marginBottom: 5 }}>Artifact保存状況</div>
                  <div style={{ fontSize: 11, color: "var(--ts)" }}>
                    PDF，領域JSON，台本，対応付け，音声，動画をproject/run単位で追跡します．
                  </div>
                </div>
                <div style={{ fontSize: 10, color: artifactCatalog.storage?.generation_blocked ? "var(--rd)" : artifactCatalog.storage?.warning ? "var(--am)" : "var(--gr)" }}>
                  {bytesText(artifactCatalog.total_artifact_bytes)} / 使用率 {((artifactCatalog.storage?.used_ratio ?? 0) * 100).toFixed(1)}%
                </div>
              </div>
              <TableSection
                title="最近のartifact"
                rows={artifactCatalog.items.slice(0, 30)}
                emptyText="artifactはまだありません"
                columns={[
                  { key: "id", label: "artifact ID", mono: true, emphasis: true },
                  { key: "owner_user_id", label: "利用者", mono: true },
                  { key: "project_name", label: "プロジェクト" },
                  { key: "generation_run_id", label: "run ID", mono: true },
                  { key: "kind", label: "種類" },
                  { key: "status", label: "状態" },
                  { key: "size_bytes", label: "サイズ", render: (row) => bytesText(row.size_bytes) },
                  { key: "created_at", label: "作成時刻", render: (row) => timeText(row.created_at) },
                ]}
              />
            </section>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 18 }}>
              <MetricCard title="生成ジョブ" value={data?.usage?.jobs_total} hint="累計ジョブ数" accent="rgba(91,141,239,.24)" tone="var(--ac)" />
              <MetricCard title="直近7日" value={data?.usage?.jobs_last_7d} hint="生成数" accent="rgba(76,175,130,.24)" tone="var(--gr)" />
              <MetricCard title="書き出し" value={data?.usage?.exports_total} hint="累計書き出し" accent="rgba(232,169,75,.24)" tone="var(--am)" />
              <MetricCard title="研究セッション" value={data?.research?.total_sessions} hint="保存済みセッション" accent="rgba(167,139,250,.24)" tone="var(--pu)" />
              <MetricCard title="ユニーク教材" value={data?.usage?.unique_materials} hint="生成参照の教材数" accent="rgba(127,224,208,.24)" tone="var(--tp)" />
              <MetricCard title="平均作業時間" value={data?.research?.analytics?.avg_active_minutes_per_session} hint="1セッションあたり" accent="rgba(110,193,255,.24)" tone="var(--ac)" suffix="分" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12, marginBottom: 18 }}>
              <BreakdownList title="モード別ジョブ数" items={jobsByMode} color="linear-gradient(90deg, #5b8def, #77a4ff)" />
              <BreakdownList title="書き出し種別" items={exportsByType} color="linear-gradient(90deg, #e8a94b, #ffd28a)" />
              <BreakdownList title="研究トリガ" items={researchByTrigger} color="linear-gradient(90deg, #a78bfa, #d1c1ff)" />
              <BreakdownList title="操作種別" items={operationTypes.slice(0, 8)} color="linear-gradient(90deg, #6ec1ff, #9fd7ff)" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12, marginBottom: 18 }}>
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

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12, marginBottom: 18 }}>
              <ActivityChart rows={dailyActivity} />
              <BreakdownList title="台本文の変更項目" items={sentenceFieldChanges} color="linear-gradient(90deg, #5b8def, #9fd7ff)" emptyText="台本文変更はまだありません" />
              <BreakdownList title="HLの変更項目" items={highlightFieldChanges} color="linear-gradient(90deg, #e8a94b, #ffd28a)" emptyText="HL変更はまだありません" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12, marginBottom: 18 }}>
              <TopSlides rows={topSlides} />
              <BreakdownList title="研究モード別" items={data?.breakdowns?.research_by_mode ?? []} color="linear-gradient(90deg, #7fe0d0, #b0f0e5)" emptyText="研究モードの記録はまだありません" />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12, marginBottom: 18 }}>
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
