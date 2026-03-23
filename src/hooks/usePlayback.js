import { useEffect, useRef } from "react";

/**
 * 再生タイマーフック
 * playing が true のとき 100ms ごとに curT を +0.1 する
 */
export function usePlayback(playing, curT, totDur, dispatch) {
  const playRef = useRef(playing);
  const curTRef = useRef(curT);
  const totRef  = useRef(totDur);

  useEffect(() => { playRef.current = playing; }, [playing]);
  useEffect(() => { curTRef.current = curT;    }, [curT]);
  useEffect(() => { totRef.current  = totDur;  }, [totDur]);

  useEffect(() => {
    if (!playing) return;
    let id;
    const tick = () => {
      if (!playRef.current) return;
      const next = curTRef.current + 0.1;
      if (next >= totRef.current) {
        dispatch({ type: "SET", k: "curT",    v: 0     });
        dispatch({ type: "SET", k: "playing", v: false });
      } else {
        dispatch({ type: "SET", k: "curT", v: next });
      }
      id = setTimeout(tick, 100);
    };
    id = setTimeout(tick, 100);
    return () => clearTimeout(id);
  }, [playing]);
}
