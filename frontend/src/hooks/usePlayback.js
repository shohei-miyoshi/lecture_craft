import { useEffect, useRef } from "react";

/**
 * 再生タイマーフック（rAF + 実時間ベース）
 *
 * seekSignal が変化したとき（シーク操作）に
 * 基準時刻をリセットすることで、再生中シークに対応する。
 */
export function usePlayback(state, dispatch, options = {}) {
  const { playing, curT, totDur, playSpeed, sents, curSl } = state;
  const { enabled = true } = options;

  // Ref経由で最新値を参照（stale closure 回避）
  const refs = useRef({ playing, curT, totDur, playSpeed, sents, curSl });
  useEffect(() => {
    refs.current = { playing, curT, totDur, playSpeed, sents, curSl };
  });

  useEffect(() => {
    if (!enabled || !playing) return;

    // 再生開始 or シーク後の基準を記録
    const startWall = Date.now();
    const startT    = refs.current.curT;
    let id;

    const tick = () => {
      const { playing: p, totDur: td, playSpeed: sp, sents: ss, curSl: cs } = refs.current;
      if (!p) return;

      const elapsed = (Date.now() - startWall) / 1000;
      const next    = startT + elapsed * sp;

      if (next >= td) {
        dispatch({ type: "SET", k: "curT",    v: td    });
        dispatch({ type: "SET", k: "playing", v: false });
        return;
      }

      dispatch({ type: "SET", k: "curT", v: next });

      // 再生位置に対応するスライドへ自動切替
      const activeSent = ss.find((s) => s.start_sec <= next && next < s.end_sec);
      if (activeSent && activeSent.slide_idx !== cs) {
        dispatch({ type: "SET_SL", v: activeSent.slide_idx });
      }

      id = requestAnimationFrame(tick);
    };

    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);

  // playing が変わるたびに再起動（シーク後に playing=true のまま seekSignal 変化させることで再起動）
  }, [enabled, playing, state.seekSignal]);  // seekSignal はシーク時にインクリメントするカウンタ
}
