import { useEffect, useRef } from "react";

/**
 * 再生タイマーフック
 * - playing が true のとき playSpeed に応じた速度で curT を進める
 * - 再生中の文に対応するスライドへ自動スクロール
 */
export function usePlayback(state, dispatch) {
  const { playing, curT, totDur, playSpeed, sents, curSl } = state;

  const playRef  = useRef(playing);
  const curTRef  = useRef(curT);
  const totRef   = useRef(totDur);
  const speedRef = useRef(playSpeed);
  const sentsRef = useRef(sents);
  const curSlRef = useRef(curSl);

  useEffect(() => { playRef.current  = playing;   }, [playing]);
  useEffect(() => { curTRef.current  = curT;       }, [curT]);
  useEffect(() => { totRef.current   = totDur;     }, [totDur]);
  useEffect(() => { speedRef.current = playSpeed;  }, [playSpeed]);
  useEffect(() => { sentsRef.current = sents;      }, [sents]);
  useEffect(() => { curSlRef.current = curSl;      }, [curSl]);

  useEffect(() => {
    if (!playing) return;

    // 実際の経過時間ベースで誤差を累積しないよう Date.now() を使う
    const startWall = Date.now();
    const startCurT = curTRef.current;
    let id;

    const tick = () => {
      if (!playRef.current) return;

      const elapsed = (Date.now() - startWall) / 1000; // 秒
      const next = startCurT + elapsed * speedRef.current;

      if (next >= totRef.current) {
        dispatch({ type: "SET", k: "curT",    v: totRef.current });
        dispatch({ type: "SET", k: "playing", v: false });
        return;
      }

      dispatch({ type: "SET", k: "curT", v: next });

      // 再生中の文に対応するスライドへ自動切替
      const activeSent = sentsRef.current.find(
        (s) => s.start_sec <= next && next < s.end_sec
      );
      if (activeSent && activeSent.slide_idx !== curSlRef.current) {
        dispatch({ type: "SET_SL", v: activeSent.slide_idx });
      }

      id = requestAnimationFrame(tick);
    };

    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [playing]);
}
