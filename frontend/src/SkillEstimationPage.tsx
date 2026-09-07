import { useEffect, useState } from "react";

type ApiFetch = (path:string, init?:RequestInit)=>Promise<Response>;
type Summary = {requested_games:number;game_count:number;estimated_rating:number;estimated_rank:string;confidence_label:string;confidence_percent:number;is_reference:boolean;average_eval_loss:number;best_move_match_rate:number;top3_match_rate:number;opening_score:number;middlegame_score:number;endgame_score:number;blunder_count:number;major_blunder_count:number;mate_opportunities:number;mate_found:number;mate_missed:number;winning_positions:number;winning_positions_converted:number;methodology:string};
type Endgame = {score:number;estimated_rank:string;mate_detection_rate:number|null;mate_missed:number;winning_conversion_rate:number|null;threat_detection_rate:null;hisshi_detection_rate:null;mate_events:Array<{opportunity_move:number;found_move:number|null;moves_to_find:number|null;shortest_mate:number;actual_mate:number|null;status:string}>};
type History = {points:Array<{game_id:number;played_at:string;estimated_rating:number;estimated_rank:string}>;current_rank:string|null;previous_rank:string|null;change:number};
type Recommendation = {title:string;priority:string;reason:string};

function SkillHistoryChart({history}:{history:History}){
  const width=760,height=250,p={top:20,right:25,bottom:42,left:55};
  const values=history.points.map(point=>point.estimated_rating);
  const min=values.length?Math.floor((Math.min(...values)-100)/100)*100:0;
  const max=values.length?Math.ceil((Math.max(...values)+100)/100)*100:100;
  const x=(i:number)=>p.left+(values.length<=1?.5:i/(values.length-1))*(width-p.left-p.right);
  const y=(v:number)=>p.top+(max-v)/Math.max(1,max-min)*(height-p.top-p.bottom);
  const path=history.points.map((point,i)=>`${i?"L":"M"} ${x(i)} ${y(point.estimated_rating)}`).join(" ");
  if(!history.points.length)return <p className="empty">棋力推移データはまだありません。</p>;
  return <div className="skill-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="推定レーティングの推移">
    {[min,(min+max)/2,max].map(value=><g key={value}><line x1={p.left} x2={width-p.right} y1={y(value)} y2={y(value)} className="chart-grid"/><text x={p.left-8} y={y(value)+4} textAnchor="end">{Math.round(value)}</text></g>)}
    <path d={path} className="chart-line"/>{history.points.map((point,i)=><g key={point.game_id} className="skill-point"><circle cx={x(i)} cy={y(point.estimated_rating)} r="5"/><title>{point.played_at}\n推定R：{point.estimated_rating}\n推定棋力：{point.estimated_rank}</title></g>)}
    <text x={p.left} y={height-10}>{history.points[0].played_at}</text><text x={width-p.right} y={height-10} textAnchor="end">{history.points.at(-1)?.played_at}</text>
  </svg></div>;
}

export default function SkillEstimationPage({apiFetch,gameId,onBack}:{apiFetch:ApiFetch;gameId:number;onBack:()=>void}){
  const [windowSize,setWindowSize]=useState(10);const [summary,setSummary]=useState<Summary|null>(null);
  const [endgame,setEndgame]=useState<Endgame|null>(null);const [history,setHistory]=useState<History|null>(null);
  const [recommendations,setRecommendations]=useState<Recommendation[]>([]);const [detail,setDetail]=useState(false);
  const [loading,setLoading]=useState(true);const [error,setError]=useState("");
  useEffect(()=>{let active=true;(async()=>{setLoading(true);setError("");try{
    // 保存済みでも再計算し、判定基準の改善を過去の棋譜へ反映する。
    const estimation=await apiFetch("/api/skill-estimation/"+gameId,{method:"POST"});if(!estimation.ok){const raw=await estimation.text();let message=raw||"棋力推定に失敗しました。";try{const body=JSON.parse(raw);if(typeof body.detail==="string")message=body.detail}catch{}throw new Error(message);}
    const [s,e,h,r]=await Promise.all([apiFetch(`/api/skill-estimation/summary?games=${windowSize}`),apiFetch(`/api/skill-estimation/endgame?games=${windowSize}`),apiFetch(`/api/skill-estimation/history?games=${windowSize}`),apiFetch(`/api/skill-estimation/recommendations?games=${windowSize}`)]);
    if(!s.ok||!e.ok||!h.ok||!r.ok)throw new Error("棋力診断を読み込めませんでした。");if(active){setSummary(await s.json());setEndgame(await e.json());setHistory(await h.json());setRecommendations((await r.json()).items)}
  }catch(reason){if(active)setError(reason instanceof Error?reason.message:"棋力推定に失敗しました。")}finally{if(active)setLoading(false)}})();return()=>{active=false}},[gameId,windowSize]);
  return <><header className="site-header"><div><span className="eyebrow">SKILL DIAGNOSIS</span><h1>棋力診断</h1></div><button className="link-button" onClick={onBack}>棋譜解析へ戻る</button></header><main className="skill-page">
    {error&&<p className="alert" role="alert">{error}</p>}{loading&&!summary&&<p className="empty">棋力を計算しています…</p>}{summary&&<>
      <section className="card skill-hero"><span className="eyebrow">あなたの推定棋力</span>{summary.is_reference&&<span className="reference-badge">参考値</span>}<strong className="skill-rank">{summary.estimated_rank}</strong><div className="skill-rating">推定R {summary.estimated_rating}</div><p>本アプリ独自の推定値（公式レーティングではありません）</p><div className="skill-confidence"><span>{summary.confidence_label}・{summary.confidence_percent}%</span><span>解析棋譜 {summary.game_count}局{summary.game_count<summary.requested_games&&`（選択${summary.requested_games}局）`}</span></div><div className="window-tabs">{[10,30,100].map(count=><button className={windowSize===count?"active":""} key={count} onClick={()=>setWindowSize(count)}>{count}局</button>)}</div><button className="detail-button" onClick={()=>setDetail(!detail)}>{detail?"詳細を閉じる":"詳細を見る"}</button>{detail&&<div className="skill-details"><span>AI第1候補一致率<strong>{summary.best_move_match_rate}%</strong></span><span>AI上位3候補以内<strong>{summary.top3_match_rate}%</strong></span><span>平均評価値損失<strong>{summary.average_eval_loss}</strong></span><span>序盤<strong>{summary.opening_score}点</strong></span><span>中盤<strong>{summary.middlegame_score}点</strong></span><span>終盤<strong>{summary.endgame_score}点</strong></span><span>悪手<strong>{summary.blunder_count}回</strong></span><span>大悪手<strong>{summary.major_blunder_count}回</strong></span></div>}</section>
      <section className="card skill-section"><h2>棋力推移</h2>{history&&<><SkillHistoryChart history={history}/><div className="history-summary"><span>現在：{history.current_rank??"–"}</span><span>30局前：{history.previous_rank??"–"}</span><strong>変化：{history.change>=0?"+":""}{history.change}</strong></div></>}</section>
      {endgame&&<section className="card skill-section"><h2>終盤力</h2><div className="endgame-score"><strong>{endgame.score}</strong> / 100</div><p>推定終盤棋力：<strong>{endgame.estimated_rank}</strong></p><div className="endgame-metrics"><span>詰み発見率<strong>{endgame.mate_detection_rate===null?"対象局面なし":`${endgame.mate_detection_rate}%`}</strong></span><span>詰み逃し<strong>{endgame.mate_missed}回</strong></span><span>勝勢維持率<strong>{endgame.winning_conversion_rate===null?"対象局面なし":`${endgame.winning_conversion_rate}%`}</strong></span></div>{endgame.mate_events.length>0&&<details><summary>詰み発見の記録</summary>{endgame.mate_events.map((event,index)=><p key={index}>詰み発生：{event.opportunity_move}手目／{event.status}{event.found_move&&`／詰み発見：${event.found_move}手目／発見まで：${event.moves_to_find}手`}</p>)}</details>}<p className="input-help">詰めろ・必至はエンジンから確実な情報を取得できないため表示していません。</p></section>}
      <section className="card skill-section"><h2>次に勉強するテーマ</h2><div className="recommendations">{recommendations.map((item,index)=><article key={item.title}><span>{index+1}</span><div><h3>{item.title}</h3><strong>{item.priority}</strong><p>{item.reason}</p></div></article>)}</div></section>
    </>}</main></>;
}
