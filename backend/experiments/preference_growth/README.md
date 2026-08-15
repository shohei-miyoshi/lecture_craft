# Preference Growth Experiment

LectureCraftの好み記憶だけを評価するローカル実験である。KGは全条件で常時有効にし、同一教材・同一比較内では同一の事前生成KGを再利用する。

## 分離方針

- 通常利用のDB・ストレージ・pipeline outputsを使用しない。
- 実行物は `local/` 以下だけに保存し、Git管理しない。
- 実験ランナーは全保存先がこのディレクトリ以下でなければ停止する。
- Git共有対象はコード、匿名化・集計済み結果、方法、引き継ぎ情報に限定する。

## パイロット

2種類の模擬ユーザについて3回の連続利用を行う。1回目は履歴なし、2・3回目は control（好みなし）と treatment（過去の好みあり）を同じ教材・同じKGで生成する。模擬ユーザの編集方針はシステムに直接与えず、編集前後だけから既存のLLM preference inductionに推定させる。

```bash
cd backend
.venv/bin/python experiments/preference_growth/run_experiment.py \
  --config experiments/preference_growth/configs/pilot.json
```

中断後に同じ `--run-id` で再実行すると、保存済みの条件を読み込み、未完了の条件から再開する。`--stop-after-round 1` でチェックポイントだけを検証できる。

生成後は以下で集計する。

```bash
.venv/bin/python experiments/preference_growth/analyze_results.py \
  --run-dir experiments/preference_growth/local/<run-id>
```

条件名を渡さない補助品質評価は以下で行う。主要評価は編集距離であり、このLLM評価だけで結論を出さない。

```bash
.venv/bin/python experiments/preference_growth/evaluate_blind.py \
  --run-dir experiments/preference_growth/local/<run-id> \
  --config experiments/preference_growth/configs/pilot.json
```

## 主要評価指標

- 模擬ユーザが完成形へ直すためのtoken-level edit distance
- 編集文率、追加・削除・置換相当量
- preference抽出成功率と非再利用分類率
- controlに対するtreatmentの編集負担削減率
- 好みの適切な反映と過剰適用（blind LLM judge。補助指標）

本パイロットは合成教材・模擬ユーザを用いた成立性確認であり、実ユーザへの一般化や教育効果を主張しない。
