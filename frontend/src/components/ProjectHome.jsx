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

export default function ProjectHome({ onCreateProject, onOpenProject, requestConfirm }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const projects = useMemo(() => listProjects(), [refreshKey]);

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
          "radial-gradient(circle at top left, rgba(91,141,239,.18), transparent 28%), radial-gradient(circle at 85% 12%, rgba(110,193,255,.12), transparent 18%), linear-gradient(180deg, rgba(255,255,255,.02), transparent 18%), var(--bg)",
      }}
    >
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 28px 44px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.15fr .85fr", gap: 18, marginBottom: 22 }}>
          <section
            style={{
              position: "relative",
              padding: 24,
              border: "1px solid rgba(110,193,255,.18)",
              background: "linear-gradient(135deg, rgba(255,255,255,.045), rgba(255,255,255,.012) 42%, rgba(91,141,239,.05) 100%)",
              boxShadow: "0 22px 50px rgba(0,0,0,.18)",
              overflow: "hidden",
            }}
          >
            <div style={{ position: "absolute", top: 0, left: 0, width: 120, height: 16, background: "linear-gradient(90deg, var(--ac), transparent)", opacity: 0.8 }} />
            <div style={{ position: "absolute", right: -36, top: 28, width: 160, height: 160, border: "1px solid rgba(110,193,255,.12)", transform: "rotate(18deg)" }} />
            <div style={{ fontSize: 11, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--ac)", marginBottom: 8 }}>
              保存済みプロジェクト
            </div>
            <div style={{ fontFamily: "var(--ff)", fontSize: 34, lineHeight: 1.1, marginBottom: 10 }}>
              プロジェクト一覧
            </div>
            <div style={{ fontSize: 13, color: "var(--ts)", lineHeight: 1.75, maxWidth: 620 }}>
              保存済みプロジェクトを開いて編集を再開するか、新しいプロジェクトを作成して講義スライドから生成を始められます。
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
              <button
                onClick={onCreateProject}
                style={{
                  padding: "10px 14px",
                  borderRadius: 12,
                  border: "1px solid rgba(110,193,255,.25)",
                  background: "var(--ac)",
                  color: "#fff",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                新しいプロジェクトを作成
              </button>
              <div
                style={{
                  padding: "10px 14px",
                  border: "1px solid var(--bd)",
                  background: "var(--s2)",
                  color: "var(--ts)",
                  fontSize: 11,
                  clipPath: "polygon(0 0, calc(100% - 14px) 0, 100% 50%, calc(100% - 14px) 100%, 0 100%, 10px 50%)",
                }}
              >
                ローカル保存件数: <span style={{ color: "var(--tp)", fontFamily: "var(--fm)" }}>{projects.length}</span>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginTop: 20 }}>
              {[
                ["再開中心", "保存済みプロジェクトからすぐ編集再開"],
                ["研究ログ", "編集の変化もあわせて保持"],
                ["書き出し連携", "動画・音声・JSON まで一続き"],
              ].map(([title, body], index) => (
                <div
                  key={title}
                  style={{
                    padding: "12px 12px 12px 16px",
                    borderLeft: `2px solid ${index === 0 ? "var(--ac)" : index === 1 ? "var(--pu)" : "var(--am)"}`,
                    background: "rgba(255,255,255,.02)",
                  }}
                >
                  <div style={{ fontSize: 11, color: "var(--tp)", marginBottom: 4 }}>{title}</div>
                  <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>{body}</div>
                </div>
              ))}
            </div>
          </section>

          <section
            style={{
              position: "relative",
              padding: 22,
              border: "1px solid var(--bd)",
              background: "linear-gradient(180deg, rgba(15,18,28,.78), rgba(15,18,28,.92))",
              boxShadow: "0 18px 40px rgba(0,0,0,.18)",
              overflow: "hidden",
            }}
          >
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(135deg, rgba(91,141,239,.08), transparent 35%, transparent 70%, rgba(110,193,255,.06))", pointerEvents: "none" }} />
            <div style={{ fontFamily: "var(--ff)", fontSize: 17, marginBottom: 12 }}>使い方</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, fontSize: 12, color: "var(--ts)", lineHeight: 1.6, position: "relative", zIndex: 1 }}>
              {[
                "新しいプロジェクトを作成して PDF をアップロード",
                "生成後に台本とハイライトを編集",
                "必要に応じて保存し、あとで再編集",
                "動画・音声・JSON として書き出し",
              ].map((text, index) => (
                <div key={text} style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 10, alignItems: "start" }}>
                  <div style={{ width: 28, height: 28, display: "grid", placeItems: "center", border: "1px solid rgba(91,141,239,.24)", background: "rgba(91,141,239,.1)", color: "var(--ac)", fontFamily: "var(--fm)", fontSize: 11 }}>
                    {index + 1}
                  </div>
                  <div style={{ paddingTop: 4 }}>{text}</div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section
          style={{
            position: "relative",
            padding: 22,
            border: "1px solid var(--bd)",
            background: "linear-gradient(180deg, rgba(15,18,28,.82), rgba(15,18,28,.9))",
            boxShadow: "0 18px 40px rgba(0,0,0,.18)",
            overflow: "hidden",
          }}
        >
          <div style={{ position: "absolute", top: 0, right: 0, width: 180, height: 18, background: "linear-gradient(270deg, rgba(110,193,255,.3), transparent)" }} />
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 14 }}>
            <div>
              <div style={{ fontFamily: "var(--ff)", fontSize: 20, marginBottom: 4 }}>保存済みプロジェクト</div>
              <div style={{ fontSize: 11, color: "var(--tm)" }}>ローカルブラウザに保存されている編集データです</div>
            </div>
            <button
              onClick={() => setRefreshKey((v) => v + 1)}
              style={{
                padding: "7px 10px",
                borderRadius: 10,
                border: "1px solid var(--bd2)",
                background: "var(--s2)",
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
                padding: "34px 18px",
                borderRadius: 18,
                border: "1px dashed var(--bd2)",
                color: "var(--tm)",
                textAlign: "center",
                fontSize: 12,
                lineHeight: 1.8,
              }}
            >
              まだ保存済みプロジェクトはありません。<br />
              「新しいプロジェクトを作成」から始めてください。
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
              {projects.map((project) => {
                const data = project.data ?? {};
                return (
                  <div
                    key={project.id}
                    style={{
                      position: "relative",
                      padding: "18px 16px 16px",
                      border: "1px solid var(--bd)",
                      background: "linear-gradient(160deg, rgba(255,255,255,.035), rgba(255,255,255,.01) 55%, rgba(91,141,239,.035))",
                      overflow: "hidden",
                    }}
                  >
                    <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: 5, background: "linear-gradient(90deg, var(--ac), rgba(110,193,255,.18), transparent 85%)" }} />
                    <div style={{ fontFamily: "var(--ff)", fontSize: 16, marginBottom: 6, wordBreak: "break-word" }}>
                      {project.name}
                    </div>
                    <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.7, marginBottom: 10 }}>
                      最終更新: {timeText(project.updated_at)}
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1.3fr .7fr", gap: 10, marginBottom: 12 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6 }}>
                      {[
                        ["スライド", data.slides?.length ?? 0],
                        ["台本", data.sentences?.length ?? 0],
                        ["枠", data.highlights?.length ?? 0],
                      ].map(([label, value]) => (
                        <div key={label} style={{ padding: "8px 9px", background: "var(--s2)", border: "1px solid rgba(255,255,255,.05)" }}>
                          <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 4 }}>{label}</div>
                          <div style={{ fontFamily: "var(--fm)", fontSize: 16, color: "var(--tp)" }}>{value}</div>
                        </div>
                      ))}
                      </div>
                      <div style={{ padding: "10px 8px", background: "rgba(91,141,239,.08)", borderLeft: "2px solid rgba(91,141,239,.28)" }}>
                        <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 6 }}>モード</div>
                        <div style={{ fontSize: 11, color: "var(--tp)" }}>{data.mode ?? "—"}</div>
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        onClick={() => onOpenProject(project)}
                        style={{
                          flex: 1,
                          padding: "8px 10px",
                          borderRadius: 10,
                          border: "1px solid rgba(110,193,255,.2)",
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
                          padding: "8px 10px",
                          borderRadius: 10,
                          border: "1px solid rgba(224,91,91,.25)",
                          background: "var(--rdd)",
                          color: "var(--rd)",
                          fontSize: 11,
                        }}
                      >
                        削除
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
