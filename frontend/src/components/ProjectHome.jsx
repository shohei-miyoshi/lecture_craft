import { useEffect, useMemo, useRef, useState } from "react";
import { deleteProject, listProjects, loadProject, updateProjectName } from "../utils/projectStore.js";

function timeText(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("ja-JP", { hour12: false });
  } catch {
    return String(value);
  }
}

function modeLabel(mode) {
  switch (mode) {
    case "audio":
      return "音声";
    case "video":
      return "動画";
    case "hl":
      return "ハイライト";
    default:
      return "未設定";
  }
}

function metricBlock(label, value, accent) {
  return (
    <div
      key={label}
      style={{
        display: "grid",
        gridTemplateColumns: "10px 1fr",
        gap: 10,
        alignItems: "center",
        padding: "10px 0",
        borderBottom: "1px solid rgba(255,255,255,.04)",
      }}
    >
      <div style={{ width: 10, height: 10, background: accent }} />
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <span style={{ fontSize: 10, color: "var(--tm)" }}>{label}</span>
        <span style={{ fontFamily: "var(--fm)", fontSize: 14, color: "var(--tp)" }}>{value}</span>
      </div>
    </div>
  );
}

function isPdfFile(file) {
  return Boolean(file && file.type === "application/pdf");
}

const bevelRadius = 8;
const bevelPanelRadius = "12px 8px 10px 8px";

function homeButtonStyle(kind = "secondary", disabled = false) {
  const styles = {
    primary: {
      border: "1px solid rgba(130,178,255,.44)",
      background: "linear-gradient(180deg, rgba(122,165,242,.98), rgba(91,141,239,.88))",
      color: "#fff",
      boxShadow: "inset 0 1px 0 rgba(255,255,255,.18), 0 10px 22px rgba(91,141,239,.22), 0 1px 0 rgba(7,8,11,.38)",
    },
    secondary: {
      border: "1px solid rgba(110,193,255,.26)",
      background: "linear-gradient(180deg, rgba(37,41,51,.98), rgba(24,27,34,.96))",
      color: "var(--tp)",
      boxShadow: "inset 0 1px 0 rgba(255,255,255,.06), 0 8px 18px rgba(0,0,0,.22), 0 1px 0 rgba(7,8,11,.42)",
    },
    subtle: {
      border: "1px solid rgba(255,255,255,.1)",
      background: "linear-gradient(180deg, rgba(34,36,43,.95), rgba(22,24,29,.95))",
      color: "var(--tp)",
      boxShadow: "inset 0 1px 0 rgba(255,255,255,.05), 0 7px 16px rgba(0,0,0,.18), 0 1px 0 rgba(7,8,11,.38)",
    },
    danger: {
      border: "1px solid rgba(224,91,91,.28)",
      background: "linear-gradient(180deg, rgba(64,31,31,.98), rgba(46,24,24,.96))",
      color: "var(--rd)",
      boxShadow: "inset 0 1px 0 rgba(255,255,255,.04), 0 7px 16px rgba(0,0,0,.16), 0 1px 0 rgba(7,8,11,.38)",
    },
  };
  const base = styles[kind] ?? styles.secondary;
  return {
    padding: "11px 16px",
    borderRadius: bevelRadius,
    fontSize: 12,
    fontWeight: 700,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.58 : 1,
    transition: "transform .12s ease, box-shadow .12s ease, opacity .12s ease",
    ...base,
  };
}

export default function ProjectHome({
  onCreateProject,
  onOpenProject,
  onResumeEditing,
  currentProject,
  onProjectDeleted,
  requestConfirm,
  requestPrompt,
  addToast,
}) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [draggingPdf, setDraggingPdf] = useState(false);
  const [pendingPdf, setPendingPdf] = useState(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("updated_desc");
  const [storedProjects, setStoredProjects] = useState([]);
  const fileInputRef = useRef(null);
  useEffect(() => {
    let active = true;
    listProjects()
      .then((rows) => {
        if (active) setStoredProjects(rows);
      })
      .catch((error) => {
        console.warn("Failed to list projects:", error);
        if (active) setStoredProjects([]);
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  const projects = useMemo(() => {
    const rows = storedProjects;
    const filtered = rows.filter((project) => {
      const q = query.trim().toLowerCase();
      if (!q) return true;
      return String(project.name ?? "").toLowerCase().includes(q);
    });
    const sorted = [...filtered];
    sorted.sort((a, b) => {
      if (sortKey === "name_asc") return String(a.name ?? "").localeCompare(String(b.name ?? ""), "ja");
      if (sortKey === "name_desc") return String(b.name ?? "").localeCompare(String(a.name ?? ""), "ja");
      if (sortKey === "updated_asc") return String(a.updated_at ?? "").localeCompare(String(b.updated_at ?? ""));
      return String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? ""));
    });
    return sorted;
  }, [query, sortKey, storedProjects]);
  const currentData = currentProject?.data ?? null;
  const currentProjectId = currentData?.project_meta?.id ?? null;
  const currentStatus = currentData?.status ?? null;
  const isGeneratingWorkspace = currentStatus === "proc";

  const handlePendingPdf = (file) => {
    if (!isPdfFile(file)) {
      if (file) addToast?.("er", "PDF ファイルを選択してください");
      return;
    }
    setPendingPdf(file);
    addToast?.("in", `📑 ${file.name}`);
  };

  const handleDelete = async (projectId) => {
    try {
      const project = await loadProject(projectId);
      if (!project) return;
      const deletingCurrentWorkspace = Boolean(currentProjectId && currentProjectId === project.id);
      requestConfirm({
        title: "プロジェクトを削除",
        message: deletingCurrentWorkspace
          ? `「${project.name}」を削除しますか？\n現在の編集中ワークスペースと自動保存データも削除されます${isGeneratingWorkspace ? "。生成中のジョブも停止します。" : "。"}`
          : `「${project.name}」を保存済みプロジェクトから削除しますか？`,
        confirmLabel: "削除",
        onConfirm: async () => {
          try {
            await deleteProject(projectId);
            if (deletingCurrentWorkspace) {
              await onProjectDeleted?.(project);
            } else {
              addToast?.("ok", `プロジェクト「${project.name}」を削除しました`);
            }
            setRefreshKey((v) => v + 1);
          } catch (error) {
            console.warn("Failed to delete project:", error);
            addToast?.("er", "プロジェクトの削除に失敗しました");
          }
        },
      });
    } catch (error) {
      console.warn("Failed to load project for deletion:", error);
      addToast?.("er", "削除対象のプロジェクトを読み込めませんでした");
    }
  };

  const handleRename = (project) => {
    requestPrompt?.({
      title: "プロジェクト名を変更",
      message: "ホーム画面で表示するプロジェクト名を変更します。",
      confirmLabel: "変更する",
      inputLabel: "プロジェクト名",
      inputInitialValue: project.name ?? "",
      inputPlaceholder: "例: パターン認識の講義",
      onConfirm: async (value) => {
        const nextName = String(value ?? "").trim();
        if (!nextName || nextName === project.name) return;
        try {
          await updateProjectName(project.id, nextName);
          setRefreshKey((v) => v + 1);
          addToast?.("ok", `プロジェクト名を「${nextName}」に変更しました`);
        } catch (error) {
          console.warn("Failed to rename project:", error);
          addToast?.("er", "プロジェクト名の変更に失敗しました");
        }
      },
    });
  };

  const startProjectWithPdf = () => {
    onCreateProject?.(pendingPdf);
  };

  const handleOpenStoredProject = async (projectId) => {
    try {
      const project = await loadProject(projectId);
      if (!project) {
        addToast?.("er", "プロジェクト本体を読み込めませんでした");
        return;
      }
      onOpenProject?.(project);
    } catch (error) {
      console.warn("Failed to open project:", error);
      addToast?.("er", "プロジェクト本体を読み込めませんでした");
    }
  };

  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        background:
          "radial-gradient(circle at 12% 12%, rgba(91,141,239,.18), transparent 22%), radial-gradient(circle at 84% 10%, rgba(110,193,255,.12), transparent 18%), linear-gradient(180deg, rgba(255,255,255,.02), transparent 16%), var(--bg)",
      }}
    >
      <div style={{ maxWidth: 1240, margin: "0 auto", padding: "26px 28px 48px" }}>
        <section
          style={{
            position: "relative",
            marginBottom: 26,
            padding: "30px 30px 26px",
            background: "linear-gradient(135deg, rgba(19,21,26,.92), rgba(19,21,26,.76) 58%, rgba(91,141,239,.08))",
            overflow: "hidden",
            border: "1px solid rgba(255,255,255,.04)",
          }}
        >
          <div style={{ position: "absolute", left: 0, top: 0, width: 180, height: 18, background: "linear-gradient(90deg, var(--ac), transparent)" }} />
          <div style={{ position: "absolute", right: -20, top: -10, width: 240, height: 240, border: "1px solid rgba(110,193,255,.12)", transform: "rotate(18deg)" }} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(180deg, rgba(255,255,255,.015) 1px, transparent 1px)", backgroundSize: "40px 40px", opacity: 0.1, pointerEvents: "none" }} />

          <div style={{ display: "grid", gridTemplateColumns: currentData ? "1.2fr .8fr" : "1fr", gap: 22, position: "relative", zIndex: 1 }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--ac)", marginBottom: 10 }}>
                プロジェクトホーム
              </div>
              <div style={{ fontFamily: "var(--ff)", fontSize: 38, lineHeight: 1.02, marginBottom: 12 }}>
                プロジェクト一覧
              </div>
              <div style={{ maxWidth: 680, fontSize: 13, color: "var(--ts)", lineHeight: 1.8 }}>
                保存済みプロジェクトを開いて編集を再開するか、新しいプロジェクトを作成して講義スライドから生成を始められます。
                研究用の編集ログや書き出しフローも、この入口からまとめて扱えます。
              </div>

              <div style={{ marginTop: 22, maxWidth: 720 }}>
                <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12, alignItems: "stretch" }}>
                  <div
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDraggingPdf(true);
                    }}
                    onDragLeave={() => setDraggingPdf(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDraggingPdf(false);
                      handlePendingPdf(e.dataTransfer.files?.[0] ?? null);
                    }}
                    onClick={() => fileInputRef.current?.click()}
                  style={{
                    position: "relative",
                    padding: "18px 18px 16px",
                    border: `1px dashed ${pendingPdf ? "rgba(76,175,130,.58)" : draggingPdf ? "rgba(110,193,255,.52)" : "rgba(110,193,255,.26)"}`,
                    background: pendingPdf
                      ? "linear-gradient(135deg, rgba(76,175,130,.16), rgba(255,255,255,.05) 55%, transparent)"
                      : draggingPdf
                        ? "linear-gradient(135deg, rgba(91,141,239,.14), rgba(255,255,255,.04))"
                        : "linear-gradient(135deg, rgba(255,255,255,.03), rgba(255,255,255,.015) 60%, transparent)",
                    cursor: "pointer",
                    overflow: "hidden",
                    borderRadius: bevelPanelRadius,
                    boxShadow: pendingPdf ? "inset 0 0 0 1px rgba(76,175,130,.18), 0 14px 28px rgba(76,175,130,.08)" : "none",
                  }}
                >
                  <div style={{ position: "absolute", left: 0, top: 0, width: 110, height: 4, background: pendingPdf ? "var(--gr)" : "var(--ac)" }} />
                  {pendingPdf && (
                    <div style={{ position: "absolute", right: 14, top: 12, padding: "3px 9px", borderRadius: 999, background: "var(--gd)", border: "1px solid rgba(76,175,130,.34)", color: "var(--gr)", fontSize: 10, fontWeight: 700 }}>
                      PDF 選択済み
                    </div>
                  )}
                  <input
                    ref={fileInputRef}
                    type="file"
                      accept=".pdf,application/pdf"
                      onChange={(e) => handlePendingPdf(e.target.files?.[0] ?? null)}
                      style={{ display: "none" }}
                  />
                  <div style={{ fontSize: 10, letterSpacing: "1.4px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>
                    講義スライドから開始
                  </div>
                  <div style={{ fontFamily: "var(--ff)", fontSize: 20, lineHeight: 1.15, marginBottom: 8 }}>
                    {pendingPdf ? "選択した PDF で新規作成" : "PDF を選んで新規作成"}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.7, marginBottom: 12 }}>
                    {pendingPdf
                      ? "この PDF を使って新しいプロジェクトを開始できます。必要ならクリックして別の PDF に差し替えられます。"
                      : "クリックまたはドロップで講義スライド PDF を選択し、そのまま編集画面へ進めます。"}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <div style={{ padding: "4px 8px", background: pendingPdf ? "rgba(76,175,130,.12)" : "rgba(255,255,255,.04)", borderLeft: `2px solid ${pendingPdf ? "rgba(76,175,130,.42)" : "rgba(110,193,255,.3)"}`, fontSize: 10, color: pendingPdf ? "var(--gr)" : "var(--tm)" }}>
                      {pendingPdf ? "準備完了" : "PDF / max 50MB"}
                    </div>
                    <div style={{ fontSize: 11, color: pendingPdf ? "var(--tp)" : "var(--tm)", fontFamily: pendingPdf ? "var(--fm)" : "inherit", fontWeight: pendingPdf ? 600 : 400 }}>
                      {pendingPdf ? pendingPdf.name : "まだ PDF は選択されていません"}
                    </div>
                  </div>
                </div>

                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", justifyContent: "flex-start", marginTop: 12 }}>
                  <button
                    onClick={startProjectWithPdf}
                    disabled={!pendingPdf}
                    style={{
                      ...homeButtonStyle("primary", !pendingPdf),
                      boxShadow: pendingPdf
                        ? "inset 0 1px 0 rgba(255,255,255,.18), 0 12px 24px rgba(91,141,239,.26), 0 1px 0 rgba(7,8,11,.38)"
                        : "inset 0 1px 0 rgba(255,255,255,.08), 0 6px 16px rgba(0,0,0,.12), 0 1px 0 rgba(7,8,11,.32)",
                    }}
                  >
                    この PDF で作成
                  </button>
                  <button
                    onClick={() => onCreateProject?.()}
                    style={homeButtonStyle("secondary")}
                  >
                    空のプロジェクトを作成
                  </button>
                </div>
              </div>
            </div>

            {currentData && (
              <div
                style={{
                  alignSelf: "stretch",
                  padding: "18px 18px 14px",
                  background: "linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.01))",
                  borderLeft: "2px solid rgba(91,141,239,.32)",
                }}
              >
                <div style={{ fontSize: 10, letterSpacing: "1.4px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>
                  現在の作業
                </div>
                <div style={{ fontFamily: "var(--ff)", fontSize: 20, lineHeight: 1.15, marginBottom: 8 }}>
                  {currentProject.name}
                </div>
                <div style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.7, marginBottom: 12 }}>
                  {isGeneratingWorkspace
                    ? "生成中のままホームに戻っています。ボタンからすぐに編集中の画面へ戻れます。"
                    : "編集中の状態を保持したままホームに戻っています。続きからすぐ再開できます。"}
                </div>
                <div style={{ marginBottom: 10 }}>
                  {[
                    ["スライド", currentData.slides?.length ?? 0, "var(--ac)"],
                    ["台本", currentData.sentences?.length ?? 0, "var(--pu)"],
                    ["枠", currentData.highlights?.length ?? 0, "var(--am)"],
                    ["モード", modeLabel(currentData.mode), "var(--gr)"],
                    ...(isGeneratingWorkspace ? [["状態", "生成中", "var(--am)"]] : []),
                  ].map(([label, value, accent]) => metricBlock(label, value, accent))}
                </div>
                <button
                  onClick={onResumeEditing}
                  style={{ ...homeButtonStyle("secondary"), width: "100%", padding: "10px 12px" }}
                >
                  {isGeneratingWorkspace ? "生成中の作業に戻る" : "直前の作業に戻る"}
                </button>
              </div>
            )}
          </div>
        </section>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.2fr) 290px", gap: 18, alignItems: "start" }}>
          <section style={{ position: "relative", paddingTop: 10 }}>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
                  <div style={{ fontFamily: "var(--ff)", fontSize: 24, lineHeight: 1.1 }}>保存済みプロジェクト</div>
                  <div style={{ padding: "2px 8px", borderRadius: 999, background: "rgba(91,141,239,.1)", color: "var(--ac)", fontFamily: "var(--fm)", fontSize: 10 }}>
                    {projects.length} 件
                  </div>
                </div>
                <div style={{ fontSize: 11, color: "var(--tm)" }}>保存済みプロジェクト一覧です。編集中ワークスペースとは別に管理されます。</div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", paddingBottom: 2 }}>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="検索"
                  style={{
                    width: 120,
                    padding: "7px 12px",
                    background: "rgba(255,255,255,.03)",
                    border: "1px solid rgba(255,255,255,.06)",
                    color: "var(--tp)",
                    fontSize: 11,
                  }}
                />
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value)}
                  style={{
                    padding: "7px 12px",
                    background: "rgba(255,255,255,.03)",
                    border: "1px solid rgba(255,255,255,.06)",
                    color: "var(--tp)",
                    fontSize: 11,
                  }}
                >
                  <option value="updated_desc">新しい順</option>
                  <option value="updated_asc">古い順</option>
                  <option value="name_asc">名前順</option>
                  <option value="name_desc">名前逆順</option>
                </select>
              </div>
            </div>

            {projects.length === 0 ? (
              <div
                style={{
                  padding: "46px 20px",
                  borderTop: "1px solid rgba(91,141,239,.2)",
                  borderBottom: "1px solid rgba(255,255,255,.05)",
                  background: "linear-gradient(90deg, rgba(91,141,239,.06), transparent 30%)",
                  color: "var(--tm)",
                  textAlign: "center",
                  fontSize: 12,
                  lineHeight: 1.9,
                }}
              >
                まだ保存済みプロジェクトはありません。<br />
                「新しいプロジェクトを作成」から始めてください。
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {projects.map((project, index) => {
                  const data = {
                    mode: project.mode,
                    slides: Array.from({ length: project.slide_count ?? 0 }),
                    sentences: Array.from({ length: project.sentence_count ?? 0 }),
                    highlights: Array.from({ length: project.highlight_count ?? 0 }),
                  };
                  return (
                    <article
                      key={project.id}
                      style={{
                        position: "relative",
                        padding: "18px 18px 16px 22px",
                        background: index % 2 === 0
                          ? "linear-gradient(90deg, rgba(255,255,255,.03), rgba(255,255,255,.012) 35%, transparent)"
                          : "linear-gradient(135deg, rgba(91,141,239,.05), rgba(255,255,255,.015) 42%, transparent)",
                        borderTop: index === 0 ? "1px solid rgba(91,141,239,.24)" : "1px solid rgba(255,255,255,.05)",
                        borderBottom: "1px solid rgba(255,255,255,.05)",
                        overflow: "hidden",
                      }}
                    >
                      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: "linear-gradient(180deg, var(--ac), rgba(110,193,255,.18))" }} />
                      <div
                        style={{
                          position: "absolute",
                          right: 16,
                          top: 0,
                          width: 52,
                          height: 14,
                          background: index % 2 === 0
                            ? "linear-gradient(90deg, rgba(110,193,255,.2), transparent)"
                            : "linear-gradient(90deg, rgba(91,141,239,.12), transparent)",
                          pointerEvents: "none",
                        }}
                      />
                      <div style={{ display: "grid", gridTemplateColumns: "1.4fr .9fr auto", gap: 16, alignItems: "center" }}>
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                            <button
                              onDoubleClick={() => handleRename(project)}
                              onClick={() => handleOpenStoredProject(project.id)}
                              style={{ border: "none", background: "none", padding: 0, color: "inherit", textAlign: "left", cursor: "pointer" }}
                            >
                              <span style={{ fontFamily: "var(--ff)", fontSize: 18, lineHeight: 1.1 }}>{project.name}</span>
                            </button>
                            <button
                              onClick={() => handleRename(project)}
                              title="名前変更"
                              style={{
                                width: 20,
                                height: 20,
                                border: "1px solid rgba(255,255,255,.08)",
                                borderRadius: "50%",
                                background: "rgba(255,255,255,.03)",
                                color: "var(--tm)",
                                fontSize: 10,
                                display: "grid",
                                placeItems: "center",
                                padding: 0,
                              }}
                            >
                              ✎
                            </button>
                            <span style={{ padding: "3px 8px", background: "rgba(91,141,239,.1)", color: "var(--ac)", fontSize: 10, fontFamily: "var(--fm)" }}>
                              {modeLabel(data.mode)}
                            </span>
                          </div>
                          <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.7 }}>
                            最終更新: {timeText(project.updated_at)}
                          </div>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
                          {[
                            ["スライド", data.slides?.length ?? 0],
                            ["台本", data.sentences?.length ?? 0],
                            ["枠", data.highlights?.length ?? 0],
                          ].map(([label, value]) => (
                            <div key={label} style={{ padding: "8px 8px 6px", background: "rgba(255,255,255,.025)", textAlign: "center" }}>
                              <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 4 }}>{label}</div>
                              <div style={{ fontFamily: "var(--fm)", fontSize: 15, color: "var(--tp)" }}>{value}</div>
                            </div>
                          ))}
                        </div>

                        <div style={{ display: "flex", gap: 8, justifySelf: "end", flexWrap: "wrap" }}>
                          <button
                            onClick={() => handleOpenStoredProject(project.id)}
                            style={{ ...homeButtonStyle("primary"), padding: "9px 12px", fontSize: 11 }}
                          >
                            開く
                          </button>
                          <button
                            onClick={() => handleDelete(project.id)}
                            style={{ ...homeButtonStyle("danger"), padding: "9px 12px", fontSize: 11 }}
                          >
                            削除
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <aside
            style={{
              position: "sticky",
              top: 18,
              padding: "18px 18px 16px",
              background: "linear-gradient(180deg, rgba(19,21,26,.9), rgba(19,21,26,.76))",
              borderTop: "1px solid rgba(91,141,239,.22)",
              borderLeft: "1px solid rgba(255,255,255,.04)",
            }}
          >
            <div style={{ position: "absolute", right: 14, top: 0, width: 44, height: 3, background: "var(--ac)" }} />
            <div style={{ fontFamily: "var(--ff)", fontSize: 18, marginBottom: 12 }}>作業の流れ</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                "新しいプロジェクトを作成して PDF をアップロード",
                "生成後に台本とハイライトを編集",
                "必要に応じて保存し、あとで再編集",
                "動画・音声・JSON として書き出し",
              ].map((text, index) => (
                <div key={text} style={{ display: "grid", gridTemplateColumns: "26px 1fr", gap: 10 }}>
                  <div style={{ width: 26, height: 26, display: "grid", placeItems: "center", background: "rgba(91,141,239,.12)", color: "var(--ac)", fontFamily: "var(--fm)", fontSize: 11 }}>
                    {index + 1}
                  </div>
                  <div style={{ paddingTop: 3, fontSize: 11, color: "var(--ts)", lineHeight: 1.65 }}>{text}</div>
                </div>
              ))}
            </div>

            <div style={{ height: 1, background: "linear-gradient(90deg, rgba(91,141,239,.24), transparent)", margin: "16px 0 14px" }} />

            <div style={{ fontSize: 10, letterSpacing: "1.3px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>
              利用メモ
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                ["再開中心", "保存済みの編集状態をあとから開いて再編集できます。"],
                ["研究ログ", "編集差分や許容・修正の履歴も残せます。"],
                ["共有枠", "1つのハイライト枠を複数の台本と対応づけられます。"],
              ].map(([title, body]) => (
                <div key={title} style={{ paddingLeft: 12, borderLeft: "2px solid rgba(110,193,255,.2)" }}>
                  <div style={{ fontSize: 11, color: "var(--tp)", marginBottom: 3 }}>{title}</div>
                  <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>{body}</div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
