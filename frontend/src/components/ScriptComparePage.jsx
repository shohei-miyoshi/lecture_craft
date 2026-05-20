import { useEffect, useMemo, useRef } from "react";
import { DETAIL_LABELS, DETAIL_VALS, DIFF_LABELS, DIFF_VALS, MODE_LABELS, MODE_VALS } from "../utils/constants.js";
import { authFetch } from "../utils/sessionStore.js";

function cardStyle() {
  return {
    border: "1px solid rgba(255,255,255,.06)",
    borderRadius: 14,
    background: "linear-gradient(180deg, rgba(255,255,255,.03), rgba(255,255,255,.01))",
    padding: 12,
  };
}

function badgeStyle(tone = "default") {
  const palette = tone === "good"
    ? { bg: "var(--gd)", bd: "rgba(76,175,130,.28)", color: "var(--gr)" }
    : tone === "accent"
      ? { bg: "rgba(122,165,242,.16)", bd: "rgba(130,178,255,.34)", color: "var(--ac)" }
      : { bg: "var(--s2)", bd: "var(--bd)", color: "var(--ts)" };
  return {
    padding: "3px 8px",
    borderRadius: 999,
    background: palette.bg,
    border: `1px solid ${palette.bd}`,
    color: palette.color,
    fontSize: 10,
  };
}

function timeText(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("ja-JP", { hour12: false });
  } catch {
    return String(value);
  }
}

function profileKeyFor({ difficulty, detail, mode }) {
  return `${difficulty}.${detail}.${mode}`;
}

function selectedProfileFromKg(row, { difficulty, detail, mode }) {
  const key = profileKeyFor({ difficulty, detail, mode });
  const profile = row?.scoring?.profiles?.[key] ?? row?.kg_result?.scoring?.selected_profile ?? null;
  return { key, profile };
}

function formatScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toFixed(3);
}

function FocusConceptPreview({ profileKey, profile }) {
  const rows = Array.isArray(profile?.top_concepts) ? profile.top_concepts : [];
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
        <div style={{ fontSize: 11, fontWeight: 700 }}>選択 profile</div>
        <span style={badgeStyle("accent")}>{profileKey}</span>
      </div>
      {rows.length === 0 ? (
        <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>
          この KG にはまだ scoring 情報がありません。KG比較ページで再生成すると表示されます。
        </div>
      ) : (
        <div style={{ display: "grid", gap: 5 }}>
          {rows.map((row, index) => (
            <div key={`${profileKey}_${row?.id ?? index}`} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "6px 8px", borderRadius: 8, border: "1px solid rgba(255,255,255,.05)", background: "rgba(255,255,255,.02)", fontSize: 10 }}>
              <span style={{ color: "var(--tp)" }}>{index + 1}. {row?.id ?? "—"}</span>
              <span style={{ color: "var(--ac)" }}>{formatScore(row?.adjusted_score)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ScriptColumn({ title, payload }) {
  const stats = payload?.stats ?? {};
  const outline = payload?.outline_json ?? {};
  const chapters = Array.isArray(outline?.chapters) ? outline.chapters : [];
  return (
    <section style={{ ...cardStyle(), minWidth: 0, display: "grid", gap: 10 }}>
      <div style={{ display: "grid", gap: 4 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "var(--tp)" }}>{title}</div>
        <div style={{ fontSize: 10, color: "var(--tm)" }}>{payload?.lecture_title ?? "—"}</div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <span style={badgeStyle()}>{stats.char_count ?? 0} 文字</span>
        <span style={badgeStyle()}>{stats.sentence_count ?? 0} 文</span>
        <span style={badgeStyle()}>{stats.line_count ?? 0} 行</span>
      </div>

      <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>アウトライン</summary>
        <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
          {chapters.length === 0 ? (
            <div style={{ fontSize: 10, color: "var(--tm)" }}>アウトラインなし</div>
          ) : (
            chapters.map((chapter) => (
              <div key={`${title}_${chapter.id}`} style={{ fontSize: 10, lineHeight: 1.6, padding: "8px 9px", borderRadius: 8, background: "rgba(255,255,255,.02)", border: "1px solid rgba(255,255,255,.05)" }}>
                <div style={{ color: "#fff", marginBottom: 4 }}>第{chapter.id}章: {chapter.title}</div>
                <div style={{ color: "var(--ts)" }}>{chapter.summary}</div>
                <div style={{ color: "var(--tm)", marginTop: 3 }}>slides: {(chapter.target_slides ?? []).join(", ") || "—"}</div>
              </div>
            ))
          )}
        </div>
      </details>

      <div style={{ fontSize: 11, fontWeight: 700 }}>台本</div>
      <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11, lineHeight: 1.8, color: "var(--tp)", fontFamily: "var(--fm)", maxHeight: 640, overflowY: "auto", padding: 12, borderRadius: 12, background: "rgba(16,18,24,.64)", border: "1px solid rgba(255,255,255,.05)" }}>
        {payload?.script_text || "—"}
      </pre>
    </section>
  );
}

export default function ScriptComparePage({
  state,
  dispatch,
  addToast,
  onOpenEditor,
  onOpenHome,
  onOpenKgCompare,
}) {
  const currentProjectId = state.projectMeta?.id ?? null;
  const previousProjectIdRef = useRef(currentProjectId);
  const kgResults = state.scriptCompareKgResults ?? [];
  const busy = Boolean(state.scriptCompareBusy);
  const loadingKg = Boolean(state.scriptCompareLoadingKg);
  const loadingHistory = Boolean(state.scriptCompareLoadingHistory);
  const error = state.scriptCompareError ?? null;
  const kgProjectId = state.scriptCompareKgProjectId ?? null;
  const historyProjectId = state.scriptCompareHistoryProjectId ?? null;
  const selectedKgResultId = state.scriptCompareSelectedKgResultId ?? "";
  const detailIdx = Number.isInteger(state.scriptCompareDetail) ? state.scriptCompareDetail : 1;
  const difficultyIdx = Number.isInteger(state.scriptCompareDifficulty) ? state.scriptCompareDifficulty : 1;
  const modeIdx = Math.max(0, MODE_VALS.indexOf(state.scriptCompareMode ?? "audio"));
  const result = state.scriptCompareResult ?? null;
  const historyItems = state.scriptCompareHistory ?? [];

  useEffect(() => {
    if (previousProjectIdRef.current === currentProjectId) return;
    previousProjectIdRef.current = currentProjectId;
    dispatch({ type: "SET", k: "scriptCompareSelectedKgResultId", v: "" });
    dispatch({ type: "SET", k: "scriptCompareKgResults", v: [] });
    dispatch({ type: "SET", k: "scriptCompareKgProjectId", v: null });
    dispatch({ type: "SET", k: "scriptCompareResult", v: null });
    dispatch({ type: "SET", k: "scriptCompareHistory", v: [] });
    dispatch({ type: "SET", k: "scriptCompareHistoryProjectId", v: null });
    dispatch({ type: "SET", k: "scriptCompareError", v: null });
  }, [currentProjectId, dispatch]);

  useEffect(() => {
    if (!currentProjectId) {
      dispatch({ type: "SET", k: "scriptCompareKgResults", v: [] });
      dispatch({ type: "SET", k: "scriptCompareKgProjectId", v: null });
      return;
    }
    if (kgProjectId === currentProjectId) return;
    let active = true;
    dispatch({ type: "SET", k: "scriptCompareLoadingKg", v: true });
    authFetch(`/api/kg-preview/results?project_id=${encodeURIComponent(currentProjectId)}&limit=30`, { method: "GET" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload) => {
        if (!active) return;
        const rows = Array.isArray(payload?.results) ? payload.results : [];
        dispatch({ type: "SET", k: "scriptCompareKgResults", v: rows });
        dispatch({ type: "SET", k: "scriptCompareKgProjectId", v: currentProjectId });
        const nextSelectedId = rows.some((row) => row?.result_id === selectedKgResultId)
          ? selectedKgResultId
          : (rows[0]?.result_id ?? "");
        dispatch({ type: "SET", k: "scriptCompareSelectedKgResultId", v: nextSelectedId });
      })
      .catch((err) => {
        if (!active) return;
        dispatch({ type: "SET", k: "scriptCompareKgResults", v: [] });
        dispatch({ type: "SET", k: "scriptCompareKgProjectId", v: null });
        dispatch({ type: "SET", k: "scriptCompareError", v: err?.message || "KG一覧の取得に失敗しました" });
      })
      .finally(() => {
        if (active) dispatch({ type: "SET", k: "scriptCompareLoadingKg", v: false });
      });
    return () => {
      active = false;
    };
  }, [currentProjectId, dispatch, kgProjectId, selectedKgResultId]);

  const selectedKg = useMemo(
    () => kgResults.find((row) => row?.result_id === selectedKgResultId) ?? null,
    [kgResults, selectedKgResultId],
  );
  const currentProfile = selectedProfileFromKg(selectedKg, {
    mode: MODE_VALS[modeIdx] ?? "audio",
    detail: DETAIL_VALS[detailIdx] ?? "standard",
    difficulty: DIFF_VALS[difficultyIdx] ?? "basic",
  });
  const resultModeIdx = Math.max(0, MODE_VALS.indexOf(result?.settings?.mode ?? ""));
  const resultDetailIdx = Math.max(0, DETAIL_VALS.indexOf(result?.settings?.detail ?? ""));
  const resultDifficultyIdx = Math.max(0, DIFF_VALS.indexOf(result?.settings?.difficulty ?? ""));

  const loadHistory = async () => {
    if (!currentProjectId) {
      dispatch({ type: "SET", k: "scriptCompareHistory", v: [] });
      dispatch({ type: "SET", k: "scriptCompareHistoryProjectId", v: null });
      return;
    }
    dispatch({ type: "SET", k: "scriptCompareLoadingHistory", v: true });
    try {
      const res = await authFetch(`/api/script-compare/results?project_id=${encodeURIComponent(currentProjectId)}&limit=20`, { method: "GET" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      dispatch({ type: "SET", k: "scriptCompareHistory", v: Array.isArray(payload?.results) ? payload.results : [] });
      dispatch({ type: "SET", k: "scriptCompareHistoryProjectId", v: currentProjectId });
    } catch (err) {
      const message = err?.message || "比較履歴の取得に失敗しました";
      dispatch({ type: "SET", k: "scriptCompareError", v: message });
      addToast?.("er", message);
    } finally {
      dispatch({ type: "SET", k: "scriptCompareLoadingHistory", v: false });
    }
  };

  useEffect(() => {
    if (!currentProjectId || historyProjectId === currentProjectId) return;
    void loadHistory();
  }, [currentProjectId, historyProjectId]);

  const openHistoryResult = async (compareId) => {
    if (!currentProjectId || !compareId) return;
    dispatch({ type: "SET", k: "scriptCompareBusy", v: true });
    dispatch({ type: "SET", k: "scriptCompareError", v: null });
    try {
      const res = await authFetch(`/api/script-compare/results/${encodeURIComponent(compareId)}?project_id=${encodeURIComponent(currentProjectId)}`, { method: "GET" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      dispatch({ type: "SET", k: "scriptCompareResult", v: payload });
      addToast?.("ok", "過去の台本比較を読み込みました");
    } catch (err) {
      const message = err?.message || "比較履歴の読み込みに失敗しました";
      dispatch({ type: "SET", k: "scriptCompareError", v: message });
      addToast?.("er", message);
    } finally {
      dispatch({ type: "SET", k: "scriptCompareBusy", v: false });
    }
  };

  const runCompare = async () => {
    if (!currentProjectId) {
      addToast?.("in", "先にプロジェクトを保存してください");
      return;
    }
    if (!selectedKgResultId) {
      addToast?.("in", "使う KG を 1 つ選んでください");
      return;
    }
    dispatch({ type: "SET", k: "scriptCompareBusy", v: true });
    dispatch({ type: "SET", k: "scriptCompareError", v: null });
    try {
      const res = await authFetch("/api/script-compare/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: currentProjectId,
          kg_result_id: selectedKgResultId,
          mode: MODE_VALS[modeIdx] ?? "audio",
          detail: DETAIL_VALS[detailIdx] ?? "standard",
          difficulty: DIFF_VALS[difficultyIdx] ?? "basic",
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      dispatch({ type: "SET", k: "scriptCompareResult", v: payload });
      void loadHistory();
      addToast?.("ok", "台本比較を生成しました");
    } catch (err) {
      const message = err?.message || "台本比較の生成に失敗しました";
      dispatch({ type: "SET", k: "scriptCompareError", v: message });
      addToast?.("er", message);
    } finally {
      dispatch({ type: "SET", k: "scriptCompareBusy", v: false });
    }
  };

  return (
    <div style={{ flex: 1, minHeight: 0, padding: 12, overflow: "hidden" }}>
      <div style={{ position: "relative", display: "grid", gridTemplateColumns: "320px minmax(0, 1fr)", gap: 12, height: "100%", minHeight: 0 }}>
        <aside style={{ minHeight: 0, overflowY: "auto", border: "1px solid rgba(255,255,255,.05)", background: "linear-gradient(180deg, rgba(19,21,26,.92), rgba(19,21,26,.82))", boxShadow: "0 24px 60px rgba(0,0,0,.18)", padding: 14 }}>
          <div style={{ fontFamily: "var(--ff)", fontSize: 18, fontWeight: 800, marginBottom: 6 }}>台本比較ページ</div>
          <div style={{ fontSize: 11, color: "var(--tm)", lineHeight: 1.7, marginBottom: 14 }}>
            保存済み KG と学習者要求を選んで、音声または動画系の通常台本フローと KG 補助付き台本フローを並べて比較します。
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
            <button onClick={onOpenHome} style={{ flex: 1, padding: "8px 10px", borderRadius: 10, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "var(--ts)", fontSize: 11, fontWeight: 700 }}>ホームへ</button>
            <button onClick={onOpenEditor} style={{ flex: 1, padding: "8px 10px", borderRadius: 10, border: "1px solid rgba(130,178,255,.38)", background: "rgba(122,165,242,.16)", color: "var(--ac)", fontSize: 11, fontWeight: 700 }}>エディタへ</button>
          </div>

          <div style={{ ...cardStyle(), marginBottom: 12 }}>
            <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 4 }}>現在の project</div>
            <div style={{ fontSize: 11, color: "var(--tp)" }}>{state.projectMeta?.name ?? "未保存プロジェクト"}</div>
            {!currentProjectId && (
              <div style={{ fontSize: 10, color: "var(--am)", lineHeight: 1.6, marginTop: 8 }}>
                このページは保存済み project に紐づいて動きます。先にプロジェクトを保存してください。
              </div>
            )}
          </div>

          <div style={{ ...cardStyle(), marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 700 }}>使う KG</div>
              <button onClick={onOpenKgCompare} style={{ padding: "4px 8px", borderRadius: 8, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "var(--ts)", fontSize: 10 }}>KG比較へ</button>
            </div>
            {loadingKg ? (
              <div style={{ fontSize: 10, color: "var(--tm)" }}>読み込み中...</div>
            ) : kgResults.length === 0 ? (
              <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>
                この project には保存済み KG がありません。先に KG 比較ページで KG を作成してください。
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8, maxHeight: 320, overflowY: "auto" }}>
                {kgResults.map((row) => {
                  const checked = row.result_id === selectedKgResultId;
                  return (
                    <button
                      key={row.result_id}
                      onClick={() => dispatch({ type: "SET", k: "scriptCompareSelectedKgResultId", v: row.result_id })}
                      style={{
                        textAlign: "left",
                        padding: 10,
                        borderRadius: 10,
                        border: `1px solid ${checked ? "rgba(130,178,255,.34)" : "rgba(255,255,255,.06)"}`,
                        background: checked ? "rgba(91,141,239,.12)" : "rgba(255,255,255,.02)",
                        color: "var(--ts)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--tp)" }}>{checked ? "✓ " : ""}{row?.variant?.label ?? "variant"}</div>
                        <div style={{ fontSize: 9, color: "var(--tm)" }}>{timeText(row?.created_at)}</div>
                      </div>
                      <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55 }}>{row?.variant?.description ?? "—"}</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                        <span style={badgeStyle()}>{row?.summary?.triplet_count ?? 0} triplet</span>
                        <span style={badgeStyle()}>{row?.summary?.node_count ?? 0} node</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div style={{ ...cardStyle(), marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>学習者要求</div>
            <div style={{ display: "grid", gap: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>提示形態</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {MODE_LABELS.map((label, idx) => (
                    <button key={label} onClick={() => dispatch({ type: "SET", k: "scriptCompareMode", v: MODE_VALS[idx] ?? "audio" })} style={{ ...badgeStyle(modeIdx === idx ? "accent" : "default"), cursor: "pointer" }}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>詳細度</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {DETAIL_LABELS.map((label, idx) => (
                    <button key={label} onClick={() => dispatch({ type: "SET", k: "scriptCompareDetail", v: idx })} style={{ ...badgeStyle(detailIdx === idx ? "accent" : "default"), cursor: "pointer" }}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>難易度</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {DIFF_LABELS.map((label, idx) => (
                    <button key={label} onClick={() => dispatch({ type: "SET", k: "scriptCompareDifficulty", v: idx })} style={{ ...badgeStyle(difficultyIdx === idx ? "accent" : "default"), cursor: "pointer" }}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div style={{ ...cardStyle(), marginBottom: 12 }}>
            <FocusConceptPreview profileKey={currentProfile.key} profile={currentProfile.profile} />
          </div>

          <div style={{ ...cardStyle(), marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 700 }}>過去の比較</div>
              <button onClick={loadHistory} style={{ padding: "4px 8px", borderRadius: 8, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "var(--ts)", fontSize: 10 }}>
                再読込
              </button>
            </div>
            {loadingHistory ? (
              <div style={{ fontSize: 10, color: "var(--tm)" }}>読み込み中...</div>
            ) : historyItems.length === 0 ? (
              <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>
                この project にはまだ台本比較の履歴がありません。
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8, maxHeight: 260, overflowY: "auto" }}>
                {historyItems.map((row) => {
                  const selected = row?.compare_id && row.compare_id === result?.compare_id;
                  const historyModeIdx = Math.max(0, MODE_VALS.indexOf(row?.settings?.mode ?? ""));
                  const historyDetailIdx = Math.max(0, DETAIL_VALS.indexOf(row?.settings?.detail ?? ""));
                  const historyDifficultyIdx = Math.max(0, DIFF_VALS.indexOf(row?.settings?.difficulty ?? ""));
                  return (
                    <button
                      key={row.compare_id}
                      onClick={() => openHistoryResult(row.compare_id)}
                      style={{
                        textAlign: "left",
                        padding: 10,
                        borderRadius: 10,
                        border: `1px solid ${selected ? "rgba(130,178,255,.34)" : "rgba(255,255,255,.06)"}`,
                        background: selected ? "rgba(91,141,239,.12)" : "rgba(255,255,255,.02)",
                        color: "var(--ts)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--tp)" }}>{selected ? "✓ " : ""}{row?.kg_result?.variant?.label ?? "比較結果"}</div>
                        <div style={{ fontSize: 9, color: "var(--tm)" }}>{timeText(row?.created_at)}</div>
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
                        <span style={badgeStyle()}>{MODE_LABELS[historyModeIdx]}</span>
                        <span style={badgeStyle()}>{DETAIL_LABELS[historyDetailIdx]}</span>
                        <span style={badgeStyle()}>{DIFF_LABELS[historyDifficultyIdx]}</span>
                      </div>
                      <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55 }}>
                        baseline {row?.baseline_stats?.char_count ?? 0} 文字 / KG {row?.kg_assisted_stats?.char_count ?? 0} 文字
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <button
            onClick={runCompare}
            disabled={busy || !currentProjectId || !selectedKgResultId}
            style={{
              width: "100%",
              padding: "10px 12px",
              borderRadius: 12,
              border: "1px solid rgba(130,178,255,.38)",
              background: busy ? "rgba(122,165,242,.28)" : "rgba(122,165,242,.18)",
              color: busy ? "#dfe8ff" : "var(--ac)",
              fontSize: 12,
              fontWeight: 800,
              cursor: busy ? "progress" : (!currentProjectId || !selectedKgResultId ? "not-allowed" : "pointer"),
            }}
          >
            {busy ? "台本比較を生成中..." : "台本比較を生成"}
          </button>

          {!!error && (
            <div style={{ marginTop: 10, fontSize: 10, color: "var(--rd)", lineHeight: 1.6 }}>
              {error}
            </div>
          )}
        </aside>

        <section style={{ minHeight: 0, overflowY: "auto", border: "1px solid rgba(255,255,255,.05)", background: "linear-gradient(180deg, rgba(19,21,26,.92), rgba(19,21,26,.82))", boxShadow: "0 24px 60px rgba(0,0,0,.22)", padding: 14 }}>
          {!result ? (
            <div style={{ padding: 16, color: "var(--tm)", fontSize: 11, lineHeight: 1.7 }}>
              保存済み KG と学習者要求を選んで「台本比較を生成」を押すと、ここに `通常台本` と `KG反映台本` が並びます。
            </div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              <div style={{ ...cardStyle(), display: "grid", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 800, color: "var(--tp)" }}>比較結果</div>
                    <div style={{ fontSize: 10, color: "var(--tm)" }}>{timeText(result.created_at)}</div>
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    <span style={badgeStyle()}>{selectedKg?.variant?.label ?? result?.kg_result?.variant?.label ?? "KG"}</span>
                    <span style={badgeStyle()}>{MODE_LABELS[resultModeIdx]}</span>
                    <span style={badgeStyle()}>{DETAIL_LABELS[resultDetailIdx]}</span>
                    <span style={badgeStyle()}>{DIFF_LABELS[resultDifficultyIdx]}</span>
                  </div>
                </div>
                <div style={{ fontSize: 10, color: "var(--ts)", lineHeight: 1.6 }}>
                  {(result.notes ?? []).join(" ")}
                </div>
                <FocusConceptPreview
                  profileKey={result?.kg_result?.scoring?.selected_profile_key ?? currentProfile.key}
                  profile={result?.kg_result?.scoring?.selected_profile ?? currentProfile.profile}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12, alignItems: "start" }}>
                <ScriptColumn title="通常台本" payload={result.baseline} />
                <ScriptColumn title="KG反映台本" payload={result.kg_assisted} />
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
