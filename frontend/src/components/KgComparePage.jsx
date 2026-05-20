import { useState } from "react";
import KgPreviewPanel from "./KgPreviewPanel.jsx";

function isPdfFile(file) {
  return Boolean(file && file.type === "application/pdf");
}

function resetKgSession(dispatch) {
  dispatch({ type: "SET", k: "kgComparisonResults", v: [] });
  dispatch({ type: "SET", k: "kgSelectedResultIds", v: [] });
  dispatch({ type: "SET", k: "kgCatalog", v: [] });
  dispatch({ type: "SET", k: "kgCatalogOpen", v: false });
  dispatch({ type: "SET", k: "kgCatalogSelection", v: [] });
  dispatch({ type: "SET", k: "kgCatalogBusy", v: false });
  dispatch({ type: "SET", k: "kgError", v: null });
  dispatch({ type: "SET", k: "kgBusy", v: false });
}

export default function KgComparePage({
  state,
  dispatch,
  pdfFile,
  setPdfFile,
  addToast,
  onOpenEditor,
  onOpenHome,
}) {
  const [dragging, setDragging] = useState(false);

  const handleFile = (file) => {
    if (!isPdfFile(file)) {
      if (file) addToast?.("er", "PDF ファイルを選択してください");
      return;
    }
    setPdfFile(file);
    resetKgSession(dispatch);
    dispatch({
      type: "APP_LOG",
      message: `KG比較ページで PDF を選択しました（file=${file.name}, size=${file.size}bytes）`,
      meta: { type: "kg_compare_pdf_select", filename: file.name, size: file.size },
    });
    addToast?.("in", `📑 ${file.name}`);
  };

  const clearPdf = () => {
    setPdfFile(null);
    resetKgSession(dispatch);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, padding: 12, overflow: "hidden" }}>
      <div
        style={{
          position: "relative",
          display: "grid",
          gridTemplateColumns: "320px minmax(0, 1fr)",
          gap: 12,
          height: "100%",
          minHeight: 0,
        }}
      >
        <aside
          style={{
            minHeight: 0,
            overflowY: "auto",
            border: "1px solid rgba(255,255,255,.05)",
            background: "linear-gradient(180deg, rgba(19,21,26,.92), rgba(19,21,26,.82))",
            boxShadow: "0 24px 60px rgba(0,0,0,.18)",
            padding: 14,
          }}
        >
          <div style={{ fontFamily: "var(--ff)", fontSize: 18, fontWeight: 800, marginBottom: 6 }}>
            KG 比較ページ
          </div>
          <div style={{ fontSize: 11, color: "var(--tm)", lineHeight: 1.7, marginBottom: 14 }}>
            講義編集画面とは分けて、KG variant の比較だけを大きく見るための専用ページです。PDF を選んで比較実行するか、保存済み結果だけを読み込んで検討できます。
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
            <button
              onClick={onOpenHome}
              style={{
                flex: 1,
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,.1)",
                background: "rgba(255,255,255,.03)",
                color: "var(--ts)",
                fontSize: 11,
                fontWeight: 700,
              }}
            >
              ホームへ
            </button>
            <button
              onClick={onOpenEditor}
              style={{
                flex: 1,
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(130,178,255,.38)",
                background: "rgba(122,165,242,.16)",
                color: "var(--ac)",
                fontSize: 11,
                fontWeight: 700,
              }}
            >
              エディタへ
            </button>
          </div>

          <div style={{ fontFamily: "var(--ff)", fontSize: 10, letterSpacing: "1.5px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>
            Source PDF
          </div>
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              handleFile(event.dataTransfer.files?.[0] ?? null);
            }}
            style={{
              position: "relative",
              border: `2px dashed ${pdfFile ? "rgba(76,175,130,.58)" : dragging ? "var(--ac)" : "var(--bd2)"}`,
              borderRadius: 16,
              padding: "18px 12px",
              textAlign: "center",
              cursor: "pointer",
              transition: "var(--tr)",
              background: pdfFile
                ? "linear-gradient(180deg, rgba(76,175,130,.14), rgba(76,175,130,.05))"
                : dragging
                  ? "var(--adim)"
                  : "none",
              boxShadow: pdfFile ? "inset 0 0 0 1px rgba(76,175,130,.18), 0 10px 24px rgba(76,175,130,.08)" : "none",
              marginBottom: 10,
            }}
          >
            <input
              key={pdfFile ? "kg-has-file" : "kg-no-file"}
              type="file"
              accept=".pdf"
              onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
              style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer" }}
            />
            <div style={{ fontSize: 22, marginBottom: 5 }}>{pdfFile ? "✅" : "🧠"}</div>
            <div style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.55 }}>
              <strong style={{ color: pdfFile ? "var(--gr)" : "var(--ac)" }}>
                {pdfFile ? "別の PDF に差し替える" : "クリック or ドロップ"}
              </strong>
              <br />
              KG 比較用の PDF を選択
            </div>
            <div style={{ fontSize: 9, color: "var(--tm)", marginTop: 5 }}>
              保存済み比較を見るには、保存済みプロジェクトを開いている必要があります
            </div>
          </div>

          {pdfFile ? (
            <div style={{ padding: "10px 11px", borderRadius: 12, border: "1px solid rgba(76,175,130,.34)", background: "linear-gradient(180deg, rgba(76,175,130,.16), rgba(76,175,130,.07))", marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: "rgba(228,230,239,.72)", marginBottom: 4 }}>現在の比較対象</div>
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--tp)", lineHeight: 1.55, wordBreak: "break-all" }}>
                {pdfFile.name}
              </div>
              <button
                onClick={clearPdf}
                style={{
                  marginTop: 8,
                  padding: "4px 8px",
                  borderRadius: 8,
                  border: "1px solid rgba(255,255,255,.1)",
                  background: "rgba(19,21,26,.6)",
                  color: "var(--tp)",
                  fontSize: 10,
                }}
              >
                クリア
              </button>
            </div>
          ) : (
            <div style={{ padding: "10px 11px", borderRadius: 12, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)", marginBottom: 14, fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>
              PDF をまだ選んでいません。新規比較を回すなら PDF を入れてください。保存済み結果の比較は、保存済みプロジェクトを開いている時だけ `保存済み結果` から確認できます。
            </div>
          )}

          <div style={{ fontFamily: "var(--ff)", fontSize: 10, letterSpacing: "1.5px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>
            Session
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            <div style={{ padding: "10px 11px", borderRadius: 12, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)" }}>
              <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 3 }}>現在の project</div>
              <div style={{ fontSize: 11, color: "var(--tp)" }}>{state.projectMeta?.name ?? "未保存プロジェクト"}</div>
            </div>
            <div style={{ padding: "10px 11px", borderRadius: 12, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)" }}>
              <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 3 }}>比較面に載っている結果</div>
              <div style={{ fontSize: 11, color: "var(--tp)" }}>{(state.kgComparisonResults ?? []).length} 件</div>
            </div>
            <div style={{ padding: "10px 11px", borderRadius: 12, border: "1px solid rgba(255,255,255,.08)", background: "rgba(255,255,255,.02)" }}>
              <div style={{ fontSize: 9, color: "var(--tm)", marginBottom: 3 }}>既定 model</div>
              <div style={{ fontSize: 11, color: "var(--tp)" }}>{state.kgDefaultModel ?? "gpt-5"}</div>
            </div>
          </div>
        </aside>

        <section
          style={{
            minHeight: 0,
            overflow: "hidden",
            border: "1px solid rgba(255,255,255,.05)",
            background: "linear-gradient(180deg, rgba(19,21,26,.92), rgba(19,21,26,.82))",
            boxShadow: "0 24px 60px rgba(0,0,0,.22)",
          }}
        >
          <KgPreviewPanel state={state} dispatch={dispatch} pdfFile={pdfFile} addToast={addToast} />
        </section>
      </div>
    </div>
  );
}
