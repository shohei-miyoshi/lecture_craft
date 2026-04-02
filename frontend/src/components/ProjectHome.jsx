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
          "radial-gradient(circle at top left, rgba(91,141,239,.18), transparent 30%), radial-gradient(circle at top right, rgba(110,193,255,.12), transparent 26%), var(--bg)",
      }}
    >
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 28px 44px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.15fr .85fr", gap: 18, marginBottom: 22 }}>
          <section
            style={{
              padding: 24,
              borderRadius: 24,
              border: "1px solid rgba(110,193,255,.18)",
              background: "linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.01))",
              boxShadow: "0 22px 50px rgba(0,0,0,.18)",
            }}
          >
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
                  borderRadius: 12,
                  border: "1px solid var(--bd)",
                  background: "var(--s2)",
                  color: "var(--ts)",
                  fontSize: 11,
                }}
              >
                ローカル保存件数: <span style={{ color: "var(--tp)", fontFamily: "var(--fm)" }}>{projects.length}</span>
              </div>
            </div>
          </section>

          <section
            style={{
              padding: 22,
              borderRadius: 24,
              border: "1px solid var(--bd)",
              background: "rgba(15,18,28,.78)",
              boxShadow: "0 18px 40px rgba(0,0,0,.18)",
            }}
          >
            <div style={{ fontFamily: "var(--ff)", fontSize: 17, marginBottom: 12 }}>使い方</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 12, color: "var(--ts)", lineHeight: 1.6 }}>
              <div>1. 新しいプロジェクトを作成して PDF をアップロード</div>
              <div>2. 生成後に台本とハイライトを編集</div>
              <div>3. 必要に応じて保存し、あとで再編集</div>
              <div>4. 動画・音声・JSON として書き出し</div>
            </div>
          </section>
        </div>

        <section
          style={{
            padding: 22,
            borderRadius: 24,
            border: "1px solid var(--bd)",
            background: "rgba(15,18,28,.82)",
            boxShadow: "0 18px 40px rgba(0,0,0,.18)",
          }}
        >
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
              {projects.map((project) => {
                const data = project.data ?? {};
                return (
                  <div
                    key={project.id}
                    style={{
                      padding: 16,
                      borderRadius: 16,
                      border: "1px solid var(--bd)",
                      background: "linear-gradient(180deg, rgba(255,255,255,.03), rgba(255,255,255,.01))",
                    }}
                  >
                    <div style={{ fontFamily: "var(--ff)", fontSize: 16, marginBottom: 6, wordBreak: "break-word" }}>
                      {project.name}
                    </div>
                    <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.7, marginBottom: 10 }}>
                      最終更新: {timeText(project.updated_at)}
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 6, marginBottom: 12 }}>
                      {[
                        ["スライド", data.slides?.length ?? 0],
                        ["台本", data.sentences?.length ?? 0],
                        ["枠", data.highlights?.length ?? 0],
                      ].map(([label, value]) => (
                        <div key={label} style={{ padding: "8px 9px", borderRadius: 10, background: "var(--s2)", border: "1px solid rgba(255,255,255,.05)" }}>
                          <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 4 }}>{label}</div>
                          <div style={{ fontFamily: "var(--fm)", fontSize: 16, color: "var(--tp)" }}>{value}</div>
                        </div>
                      ))}
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
