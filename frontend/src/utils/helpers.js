/** 秒数を m:ss 形式にフォーマット */
export const fmt = (s) => {
  const sec = Math.floor(s % 60);
  const m   = Math.floor(s / 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
};

/** 数値を四捨五入 */
export const rn = (v) => Math.round(v);

/** File → base64文字列 (pdf_base64 用) */
export const toB64 = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result.split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });

/** デモ用データ生成 */
export function makeDemo() {
  const cols   = ["#1a2340", "#1f2d1f", "#2d1f1f", "#1f1f2d", "#2d2820"];
  const titles = ["パターン認識とは？", "特徴量の設計", "分類器の評価", "音声認識への応用", "まとめ"];
  const slides = titles.map((t, i) => ({
    id: `sl${i}`,
    title: t,
    color: cols[i],
    image_base64: null,
    width: 1600,
    height: 900,
    aspect_ratio: 16 / 9,
  }));
  const sentences = [
    { id: "s1",  slide_idx: 0, text: "パターン認識とは、コンピュータにパターンの同一性と相違性を理解させることです。", start_sec: 0,  end_sec: 5  },
    { id: "s2",  slide_idx: 0, text: "たとえばリンゴとミカンを考えると、果物という観点では同じ分類になりますが、色や形では異なります。", start_sec: 5,  end_sec: 11 },
    { id: "s3",  slide_idx: 0, text: "何を同じと見なすかを先に定め、その観点に沿ってデータから判断基準を機械に学ばせるのが基本です。", start_sec: 11, end_sec: 17 },
    { id: "s4",  slide_idx: 1, text: "特徴量とは、分類に役立つデータの数値的な表現です。", start_sec: 18, end_sec: 23 },
    { id: "s5",  slide_idx: 1, text: "良い特徴量は、クラス間で大きく異なり、クラス内では小さくまとまる性質を持ちます。", start_sec: 23, end_sec: 30 },
    { id: "s6",  slide_idx: 2, text: "分類器の性能は、正解率・適合率・再現率などの指標で評価します。", start_sec: 31, end_sec: 37 },
    { id: "s7",  slide_idx: 2, text: "交差検証を用いることで、限られたデータでも汎化性能を推定できます。", start_sec: 37, end_sec: 44 },
    { id: "s8",  slide_idx: 3, text: "音声認識では音声波形をMFCCなどの特徴量に変換し、パターンとして分類します。", start_sec: 45, end_sec: 52 },
    { id: "s9",  slide_idx: 4, text: "本講義では、パターン認識の基礎から応用まで体系的に学習しました。", start_sec: 53, end_sec: 58 },
    { id: "s10", slide_idx: 4, text: "次回は深層学習を用いたより高度な手法について学びます。", start_sec: 58, end_sec: 63 },
  ];
  const highlights = [
    { id: "h1", sid: "s2", slide_idx: 0, kind: "marker", x: 15, y: 28, w: 65, h: 42 },
    { id: "h2", sid: "s3", slide_idx: 0, kind: "box",    x: 10, y: 74, w: 80, h: 16 },
    { id: "h3", sid: "s5", slide_idx: 1, kind: "arrow",  x: 20, y: 38, w: 60, h: 32 },
    { id: "h4", sid: "s6", slide_idx: 2, kind: "marker", x: 10, y: 20, w: 75, h: 50 },
    { id: "h5", sid: "s8", slide_idx: 3, kind: "box",    x: 15, y: 54, w: 55, h: 26 },
  ];
  return { slides, sentences, highlights, total_duration: 65 };
}
