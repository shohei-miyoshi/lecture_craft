const REGION_PALETTE = [
  { color: "#6ec1ff", bg: "rgba(110,193,255,.16)", bgStrong: "rgba(110,193,255,.28)" },
  { color: "#ffb86b", bg: "rgba(255,184,107,.16)", bgStrong: "rgba(255,184,107,.28)" },
  { color: "#8fe388", bg: "rgba(143,227,136,.16)", bgStrong: "rgba(143,227,136,.28)" },
  { color: "#f48fb1", bg: "rgba(244,143,177,.16)", bgStrong: "rgba(244,143,177,.28)" },
  { color: "#c3a6ff", bg: "rgba(195,166,255,.16)", bgStrong: "rgba(195,166,255,.28)" },
  { color: "#7fe0d0", bg: "rgba(127,224,208,.16)", bgStrong: "rgba(127,224,208,.28)" },
];

export function getHighlightRegionMeta(highlights = [], highlightId = null) {
  if (!highlightId) {
    return {
      index: null,
      label: "HLなし",
      shortLabel: "HLなし",
      color: "var(--tm)",
      bg: "var(--s3)",
      bgStrong: "var(--s2)",
      border: "rgba(255,255,255,.14)",
    };
  }

  const index = Math.max(0, (highlights ?? []).findIndex((item) => item.id === highlightId));
  const palette = REGION_PALETTE[index % REGION_PALETTE.length];
  const regionNumber = index + 1;
  return {
    index: regionNumber,
    label: `領域${regionNumber}`,
    shortLabel: `領域${regionNumber}`,
    color: palette.color,
    bg: palette.bg,
    bgStrong: palette.bgStrong,
    border: palette.color,
  };
}
