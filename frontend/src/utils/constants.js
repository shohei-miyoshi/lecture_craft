export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const DETAIL_VALS   = ["summary", "standard", "detail"];
export const DIFF_VALS     = ["intro", "basic", "advanced"];
export const DETAIL_LABELS = ["要約的", "標準的", "精緻"];
export const DIFF_LABELS   = ["入門", "基礎", "発展"];

/** ハイライト種別の表示名 */
export const KIND_LABEL = { marker: "マーカー", arrow: "矢印", box: "囲み" };

/** ハイライト種別の色 */
export const KIND_COLOR = { marker: "#5b8def", arrow: "#4caf82", box: "#e8a94b" };

/** ハイライト種別の背景色（通常） */
export const KIND_BG = {
  marker: "rgba(91,141,239,.14)",
  arrow:  "rgba(76,175,130,.14)",
  box:    "rgba(232,169,75,.14)",
};

/** ハイライト種別の背景色（選択時） */
export const KIND_BG_SEL = {
  marker: "rgba(91,141,239,.28)",
  arrow:  "rgba(76,175,130,.28)",
  box:    "rgba(232,169,75,.28)",
};
