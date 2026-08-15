# Codex handoff

- 作業ブランチ: `codex/preference-memory-pilot`
- 九大サーバ・公開環境: 未反映。ローカル実験のみ。
- KG: 全条件で `global_slide`。評価対象ではない。
- 評価対象: 編集履歴からの好み抽出と二回目以降の台本生成への反映。
- 生データ: `local/`（Git管理外）。通常利用データと混ぜない。
- `pilot-20260815-a` の実験runnerは抽出済みpreferenceだけを渡しており、生の編集前後は渡していない。監査を契機に本番経路も同じ制約へ強化した。
- 再現方法と限界: `README.md` と `PROTOCOL.md` を参照。
- 集計済みパイロット結果: `reports/pilot-20260815.md`。生データはlocalにのみ保持。
- Gitへ上げる際は、集計値が実測か例示かを明記し、生のAPI応答や動画を不用意に含めない。
