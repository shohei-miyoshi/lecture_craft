# Codex handoff

- 作業ブランチ: `codex/preference-memory-pilot`
- 九大サーバ・公開環境: 未反映。ローカル実験のみ。
- KG: 全条件で `global_slide`。評価対象ではない。
- 評価対象: 編集履歴からの好み抽出と二回目以降の台本生成への反映。
- 生データ: `local/`（Git管理外）。通常利用データと混ぜない。
- `pilot-20260815-a` は定義重視・具体例重視・結論先行・簡潔さ重視の4模擬ユーザ、各3回で完了。8対応比較の平均相対編集負担削減率は32.1%だが、具体例重視3回目は23.9%悪化した。
- 実験runnerは抽出済みpreferenceだけを渡しており、生の編集前後は渡していない。監査を契機に本番経路も同じ制約へ強化した。
- 編集前後・理由・gold category・抽出結果は `build_process_report.py` で `local/<run-id>/reports/process_and_edit_examples.{md,json}` に再生成できる。生データなのでGit管理外。
- 結論先行のblind judgeは「好みの過剰適用」と「教材外情報」を混同したため、当該overapplication数は解釈しない。失敗として集計レポートに明記済み。
- 再現方法と限界: `README.md` と `PROTOCOL.md` を参照。
- 集計済みパイロット結果: `reports/pilot-20260815.md`。生データはlocalにのみ保持。
- Gitへ上げる際は、集計値が実測か例示かを明記し、生のAPI応答や動画を不用意に含めない。
