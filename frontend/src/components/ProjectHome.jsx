import { useMemo, useState } from "react";
import { deleteProject, listProjects, loadProject } from "../utils/projectStore.js";

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

export default function ProjectHome({
  onCreateProject,
  onOpenProject,
  onResumeEditing,
  currentProject,
  requestConfirm,
}) {
  const [refreshKey, setRefreshKey] = useState(0);
  const projects = useMemo(() => listProjects(), [refreshKey]);
  const currentData = currentProject?.data ?? null;

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

              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 18 }}>
                <button
                  onClick={onCreateProject}
                  style={{
                    padding: "11px 16px",
                    border: "1px solid rgba(110,193,255,.28)",
                    background: "var(--ac)",
                    color: "#fff",
                    fontSize: 12,
                    fontWeight: 700,
                    boxShadow: "0 14px 30px rgba(91,141,239,.24)",
                  }}
                >
                  新しいプロジェクトを作成
                </button>
                <div
                  style={{
                    padding: "11px 14px",
                    background: "rgba(255,255,255,.03)",
                    color: "var(--ts)",
                    fontSize: 11,
                    borderLeft: "2px solid rgba(110,193,255,.24)",
                  }}
                >
                  ローカル保存件数: <span style={{ color: "var(--tp)", fontFamily: "var(--fm)" }}>{projects.length}</span>
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
                <div style={{ fontFamily: "var(--ff)", fontSize: 24, lineHeight: 1.1, marginBottom: 4 }}>保存済みプロジェクト</div>
                <div style={{ fontSize: 11, color: "var(--tm)" }}>ローカルブラウザに保存されている編集データです</div>
              </div>
              <button
                onClick={() => setRefreshKey((v) => v + 1)}
                style={{
                  padding: "7px 11px",
                  border: "1px solid var(--bd2)",
                  background: "rgba(255,255,255,.03)",
                  color: "var(--tp)",
                  fontSize: 11,
                }}
              >
                更新
              </button>
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
                        background: "linear-gradient(90deg, rgba(255,255,255,.03), rgba(255,255,255,.012) 35%, transparent)",
                        borderTop: index === 0 ? "1px solid rgba(91,141,239,.24)" : "1px solid rgba(255,255,255,.05)",
                        borderBottom: "1px solid rgba(255,255,255,.05)",
                        overflow: "hidden",
                      }}
                    >
                      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: "linear-gradient(180deg, var(--ac), rgba(110,193,255,.18))" }} />
                      <div style={{ display: "grid", gridTemplateColumns: "1.4fr .9fr auto", gap: 16, alignItems: "center" }}>
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                            <div style={{ fontFamily: "var(--ff)", fontSize: 18, lineHeight: 1.1 }}>{project.name}</div>
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

                        <div style={{ display: "flex", gap: 8, justifySelf: "end" }}>
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
            }}
          >
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
