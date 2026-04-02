import { useMemo, useRef, useState } from "react";
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

export default function ProjectHome({
  onCreateProject,
  onOpenProject,
  onResumeEditing,
  currentProject,
  requestConfirm,
  requestPrompt,
  addToast,
}) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [draggingPdf, setDraggingPdf] = useState(false);
  const [pendingPdf, setPendingPdf] = useState(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("updated_desc");
  const fileInputRef = useRef(null);
  const projects = useMemo(() => {
    const rows = listProjects();
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
  }, [query, refreshKey, sortKey]);
  const currentData = currentProject?.data ?? null;

  const handlePendingPdf = (file) => {
    if (!isPdfFile(file)) {
      if (file) addToast?.("er", "PDF ファイルを選択してください");
      return;
    }
    setPendingPdf(file);
    addToast?.("in", `📑 ${file.name}`);
  };

  const handleDelete = (projectId) => {
    const project = loadProject(projectId);
    if (!project) return;
    requestConfirm({
      title: "プロジェクトを削除",
      message: `「${project.name}」をローカル保存から削除しますか？`,
      confirmLabel: "削除",
      onConfirm: () => {
        deleteProject(projectId);
        setRefreshKey((v) => v + 1);
      },
    });
  };

  const handleRename = (project) => {
    requestPrompt?.({
      title: "プロジェクト名を変更",
      message: "ホーム画面で表示するプロジェクト名を変更します。",
      confirmLabel: "変更する",
      inputLabel: "プロジェクト名",
      inputInitialValue: project.name ?? "",
      inputPlaceholder: "例: パターン認識の講義",
      onConfirm: (value) => {
        const nextName = String(value ?? "").trim();
        if (!nextName || nextName === project.name) return;
        updateProjectName(project.id, nextName);
        setRefreshKey((v) => v + 1);
        addToast?.("ok", `プロジェクト名を「${nextName}」に変更しました`);
      },
    });
  };

  const startProjectWithPdf = () => {
    onCreateProject?.(pendingPdf);
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
          }}
        >
          <div style={{ position: "absolute", left: 0, top: 0, width: 180, height: 18, background: "linear-gradient(90deg, var(--ac), transparent)" }} />
          <div style={{ position: "absolute", right: -20, top: -10, width: 240, height: 240, border: "1px solid rgba(110,193,255,.12)", transform: "rotate(18deg)" }} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(180deg, rgba(255,255,255,.015) 1px, transparent 1px)", backgroundSize: "40px 40px", opacity: 0.1, pointerEvents: "none" }} />

          <div style={{ display: "grid", gridTemplateColumns: currentData ? "1.2fr .8fr" : "1fr", gap: 22, position: "relative", zIndex: 1 }}>
            <div>
              <div style={{ fontSize: 11, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--ac)", marginBottom: 10 }}>
                Project Index
              </div>
              <div style={{ fontFamily: "var(--ff)", fontSize: 38, lineHeight: 1.02, marginBottom: 12 }}>
                プロジェクト一覧
              </div>
              <div style={{ maxWidth: 680, fontSize: 13, color: "var(--ts)", lineHeight: 1.8 }}>
                保存済みプロジェクトを開いて編集を再開するか、新しいプロジェクトを作成して講義スライドから生成を始められます。
                研究用の編集ログや書き出しフローも、この入口からまとめて扱えます。
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 420px) auto", gap: 16, alignItems: "end", marginTop: 22 }}>
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
                    border: `1px dashed ${draggingPdf ? "rgba(110,193,255,.52)" : "rgba(110,193,255,.26)"}`,
                    background: draggingPdf
                      ? "linear-gradient(135deg, rgba(91,141,239,.14), rgba(255,255,255,.04))"
                      : "linear-gradient(135deg, rgba(255,255,255,.03), rgba(255,255,255,.015) 60%, transparent)",
                    cursor: "pointer",
                    overflow: "hidden",
                  }}
                >
                  <div style={{ position: "absolute", left: 0, top: 0, width: 110, height: 4, background: "var(--ac)" }} />
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
                    PDF を選んで新規作成
                  </div>
                  <div style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.7, marginBottom: 12 }}>
                    クリックまたはドロップで講義スライド PDF を選択し、そのまま編集画面へ進めます。
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <div style={{ padding: "4px 8px", background: "rgba(255,255,255,.04)", borderLeft: "2px solid rgba(110,193,255,.3)", fontSize: 10, color: "var(--tm)" }}>
                      PDF / max 50MB
                    </div>
                    <div style={{ fontSize: 11, color: pendingPdf ? "var(--tp)" : "var(--tm)", fontFamily: pendingPdf ? "var(--fm)" : "inherit" }}>
                      {pendingPdf ? pendingPdf.name : "まだ PDF は選択されていません"}
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", justifyContent: "flex-start" }}>
                  <button
                    onClick={startProjectWithPdf}
                    disabled={!pendingPdf}
                    style={{
                      padding: "11px 16px",
                      border: "1px solid rgba(110,193,255,.28)",
                      background: pendingPdf ? "var(--ac)" : "rgba(91,141,239,.2)",
                      color: "#fff",
                      fontSize: 12,
                      fontWeight: 700,
                      boxShadow: pendingPdf ? "0 14px 30px rgba(91,141,239,.24)" : "none",
                      opacity: pendingPdf ? 1 : 0.55,
                      cursor: pendingPdf ? "pointer" : "not-allowed",
                    }}
                  >
                    この PDF で作成
                  </button>
                  <button
                    onClick={() => onCreateProject?.()}
                    style={{
                      padding: "11px 16px",
                      border: "1px solid rgba(110,193,255,.22)",
                      background: "rgba(255,255,255,.05)",
                      color: "var(--tp)",
                      fontSize: 12,
                      fontWeight: 700,
                    }}
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
                  Current Workspace
                </div>
                <div style={{ fontFamily: "var(--ff)", fontSize: 20, lineHeight: 1.15, marginBottom: 8 }}>
                  {currentProject.name}
                </div>
                <div style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.7, marginBottom: 12 }}>
                  編集中の状態を保持したままホームに戻っています。続きからすぐ再開できます。
                </div>
                <div style={{ marginBottom: 10 }}>
                  {[
                    ["スライド", currentData.slides?.length ?? 0, "var(--ac)"],
                    ["台本", currentData.sentences?.length ?? 0, "var(--pu)"],
                    ["枠", currentData.highlights?.length ?? 0, "var(--am)"],
                    ["モード", modeLabel(currentData.mode), "var(--gr)"],
                  ].map(([label, value, accent]) => metricBlock(label, value, accent))}
                </div>
                <button
                  onClick={onResumeEditing}
                  style={{
                    width: "100%",
                    padding: "10px 12px",
                    border: "1px solid rgba(110,193,255,.26)",
                    background: "rgba(91,141,239,.12)",
                    color: "var(--tp)",
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  いまの編集を続ける
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
                <div style={{ fontSize: 11, color: "var(--tm)" }}>ローカルブラウザに保存されている編集データです</div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", paddingBottom: 2 }}>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="検索"
                  style={{ width: 110, padding: "6px 8px", background: "transparent", border: "none", borderBottom: "1px solid var(--bd2)", color: "var(--tp)", fontSize: 11 }}
                />
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value)}
                  style={{ padding: "5px 4px", background: "transparent", border: "none", borderBottom: "1px solid var(--bd2)", color: "var(--tp)", fontSize: 11 }}
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
                  const data = project.data ?? {};
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
                              onClick={() => onOpenProject(project)}
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
                            <span style={{ padding: "3px 7px", background: "rgba(91,141,239,.1)", color: "var(--ac)", fontSize: 10, fontFamily: "var(--fm)" }}>
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
                            onClick={() => onOpenProject(project)}
                            style={{
                              padding: "9px 12px",
                              border: "1px solid rgba(110,193,255,.22)",
                              background: "var(--ac)",
                              color: "#fff",
                              fontSize: 11,
                              fontWeight: 700,
                            }}
                          >
                            開く
                          </button>
                          <button
                            onClick={() => handleDelete(project.id)}
                            style={{
                              padding: "9px 12px",
                              border: "1px solid rgba(224,91,91,.24)",
                              background: "var(--rdd)",
                              color: "var(--rd)",
                              fontSize: 11,
                            }}
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
              Workspace Notes
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
