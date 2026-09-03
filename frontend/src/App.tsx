import { FormEvent, useCallback, useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";
import SkillEstimationPage from "./SkillEstimationPage";

type Game = { id:number; owner_id:number|null; owner_email:string|null; original_filename:string; event_name:string|null; sente_name:string|null; gote_name:string|null; played_at:string; user_side:"SENTE"|"GOTE"; is_public:boolean; professional_name_suspected:boolean; professional_name_matches:string[]; analysis_status:string; analysis_error?:string|null; critical_position_count:number };
type AiSubscription = { active:boolean; trial_available:boolean; permanent_access:boolean; status:string; current_period_end:string|null; monthly_price_yen:number; trial_days:number; test_toggle_available:boolean };
type Rewards = { rewards_enabled:boolean; reward_per_game_yen:number; pending_yen:number; fixed_yen:number; payout_available_yen:number; approved_games:number; minimum_payout_yen:number };
type User = { id:number; email:string; is_admin:boolean; mfa_enabled:boolean; android_apk_download_allowed:boolean; global_game_viewer:boolean; is_anonymous:boolean };
type Position = { id:number; move_number:number; japanese_move:string; evaluation_before:number|null; evaluation_after:number|null; selection_reason:string|null; principal_variation:string[]|null; engine_explanation_visible:boolean };
type AiComment = { id:number; critical_position_id:number; move_number:number; generated_text:string; current_text:string; model_version:string; updated_at:string };
type SearchResult = { source_type:string; source_id:number; game_id:number; move_number:number|null; move_count:number|null; title:string; text:string; event_name:string|null; score:number; backend:string };
type Answer = { critical_position_id:number; question_number:number; answer_text:string };
type Submission = { id:number; review_status:string; submitted_at:string|null; answers:(Answer & {id:number})[] };
type ReviewItem = { id:number; game_id:number; status:string; snapshot:{positions:{id:number;move_number:number;move:string}[];answers:Answer[]}|null };
type AdminUser = { id:number;email:string;email_verified:boolean;is_admin:boolean;created_at:string;game_count:number;ai_access_active:boolean;permanent_access:boolean;subscription_status:string;current_period_end:string|null };
type AdminGame = { id:number;user_id:number;user_email:string;original_filename:string;event_name:string|null;sente_name:string|null;gote_name:string|null;played_at:string;user_side:"SENTE"|"GOTE";is_public:boolean;move_count:number;analysis_status:string;critical_position_count:number;created_at:string;best_move_match_rate:number|null;match_rate_analyzed_moves:number;professional_level_deletion_candidate:boolean;professional_name_suspected:boolean;professional_name_matches:string[] };
type AdminBranch = { id:number;name:string;base_move_number:number;usi_moves:string[];japanese_moves:string[];board:PlaybackFrame["board"] };
type BoardPiece = { symbol:string; owner:"SENTE"|"GOTE" };
type PlaybackComment = { question_number:number; question:string; answer:string };
type EngineVariation = { evaluation:number|null; mate_in:number|null; principal_variation:string[] };
type PlaybackFrame = { move_number:number; usi_move:string|null; japanese_move:string; board:{squares:(BoardPiece|null)[][];hands:{SENTE:{symbol:string;count:number}[];GOTE:{symbol:string;count:number}[]};turn:"SENTE"|"GOTE"};evaluation:number|null;win_rate:number|null;principal_variation:string[]|null;variations:EngineVariation[]|null;engine_name:string|null;engine_version:string|null;evaluation_function:string|null;is_critical:boolean;selection_reason:string|null;comments:PlaybackComment[] };
type Playback = { game_id:number; filename:string; event_name:string|null; sente_name:string|null; gote_name:string|null; user_side:"SENTE"|"GOTE"; submitted:boolean; test_evaluation_toggle_available:boolean; ai_visible:boolean; frames:PlaybackFrame[] };
type BranchMove = { usi:string; from_square:string|null; to_square:string; drop_piece:string|null; promote:boolean; japanese_move:string };
type BranchPosition = { board:PlaybackFrame["board"];turn:"SENTE"|"GOTE";moves:string[];japanese_moves:string[];legal_moves:BranchMove[];game_over:boolean };
type BranchAnalysisVariation = { evaluation:number|null;mate_in:number|null;principal_variation:string[];usi_principal_variation:string[] };
type BranchAnalysis = { evaluation:number|null;mate_in:number|null;win_rate:number;engine_name:string;engine_version:string;evaluation_function:string|null;variations:BranchAnalysisVariation[] };
type SavedBranch = { id:number;game_id:number;name:string;base_move_number:number;usi_moves:string[];japanese_moves:string[];created_at:string;updated_at:string };

const statusLabels:Record<string,string>={QUEUED:"解析待ち",ANALYZING:"解析中",COMMENT_REQUIRED:"コメント待ち",FAILED:"解析失敗"};
const questions=["この局面で何を考えていましたか？","どの候補手を比較しましたか？","今振り返ると、判断の原因は何だったと思いますか？"];
const emptyRewards:Rewards={rewards_enabled:true,reward_per_game_yen:300,pending_yen:0,fixed_yen:0,payout_available_yen:0,approved_games:0,minimum_payout_yen:10000};
const answerKey=(positionId:number, question:number)=>positionId+"-"+question;
const normalizePath=(path:string)=>path.length>1&&path.endsWith("/")?path.slice(0,-1):path;
const siteUrl="https://kifu-comment-lab.com";
const isNativeAndroid=Capacitor.getPlatform()==="android";
const seoByPath:Record<string,{title:string;description:string}>={
  "/":{
    title:"無料の将棋棋譜解析アプリ｜棋譜コメント研究所",
    description:"KIF・KI2・CSA・USI対応の将棋棋譜解析アプリ。AIが重要局面を抽出し、盤面再生、評価値、棋力診断で対局の振り返りを支援します。基本機能は無料です。",
  },
  "/service":{
    title:"将棋棋譜解析アプリの機能・料金｜棋譜コメント研究所",
    description:"無料で使える将棋棋譜解析アプリの機能と料金をご案内。重要局面の自動抽出、盤面再生、評価値、振り返りコメント、棋力診断に対応しています。",
  },
};
function setMeta(selector:string,attribute:string,value:string){
  const element=document.head.querySelector<HTMLMetaElement>(selector);
  if(element)element.setAttribute(attribute,value);
}
function PasswordField({id,name="password",label,autoComplete,minLength}:{id:string;name?:string;label:string;autoComplete:"current-password"|"new-password";minLength?:number}){
  const [visible,setVisible]=useState(false);
  return <div className="password-field"><label htmlFor={id}>{label}</label><div className="password-input-wrap"><input id={id} name={name} type={visible?"text":"password"} autoComplete={autoComplete} minLength={minLength} required/><button type="button" className="password-toggle" aria-label={visible?"パスワードを非表示にする":"パスワードを表示する"} aria-pressed={visible} onClick={()=>setVisible(value=>!value)}>{visible?"非表示":"表示"}</button></div></div>;
}
function ShogiHomeButton({onActivate}:{onActivate:()=>void}){
  return <button type="button" className="shogi-home-button" onClick={onActivate} aria-label="トップページへ戻る"><span aria-hidden="true">玉</span><small>トップ</small></button>;
}
function HeroShogiPieces(){
  return <div className="hero-shogi-pieces" aria-hidden="true"><img src="/hero/shogi-pieces-3d-v2.png" alt=""/></div>;
}
function LegacyPublicSearch(){
  const [query,setQuery]=useState("");
  const [results,setResults]=useState<SearchResult[]>([]);
  const [busy,setBusy]=useState(false);
  const [searched,setSearched]=useState(false);
  const [error,setError]=useState("");
  async function search(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const normalized=query.trim();if(!normalized)return;
    setBusy(true);setError("");
    try{
      const response=await fetch("/api/search/public?q="+encodeURIComponent(normalized));
      if(!response.ok)throw new Error("公開データを検索できませんでした。");
      const body:{results:SearchResult[]}=await response.json();setResults(body.results);setSearched(true);
    }catch(reason){setError(reason instanceof Error?reason.message:"検索に失敗しました。")}finally{setBusy(false)}
  }
  return <main className="public-search-page"><section className="card public-search-card"><div><span className="eyebrow">PUBLIC SEARCH</span><h2>公開棋譜・コメントを検索</h2><p>投稿者が公開に設定した棋譜、重要局面、提出済みの匿名コメントを検索できます。</p></div><form onSubmit={search}><label htmlFor="public-search">キーワード</label><div className="search-input-row"><input id="public-search" type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="例：終盤、詰み、飛車を切る" maxLength={200}/><button disabled={busy||!query.trim()}>{busy?"検索中…":"公開データを検索"}</button></div></form>{error&&<p className="alert" role="alert">{error}</p>}{searched&&results.length===0&&<p className="empty">一致する公開データはありません。</p>}{results.length>0&&<div className="search-results" aria-live="polite">{results.map(result=><article className="public-search-result" key={result.source_type+"-"+result.source_id}><strong>{result.title}</strong><span>{result.event_name??"棋戦名不明"}{result.move_number!==null?"・"+result.move_number+"手目":""}</span><p>{result.text||"公開情報はありません。"}</p><small>{result.source_type==="game"?"公開棋譜":result.source_type==="critical_position"?"重要局面":"匿名コメント"}</small></article>)}</div>}</section></main>;
}
function PublicSearch(){
  const [query,setQuery]=useState("");
  const [tesu,setTesu]=useState("");
  const [results,setResults]=useState<SearchResult[]>([]);
  const [busy,setBusy]=useState(false),[searched,setSearched]=useState(false),[error,setError]=useState("");
  async function search(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const normalized=query.trim();if(!normalized&&!tesu)return;
    setBusy(true);setError("");
    try{
      const params=new URLSearchParams();if(normalized)params.set("keyword",normalized);if(tesu)params.set("tesu",tesu);
      const response=await fetch("/api/search/public?"+params.toString());
      if(!response.ok)throw new Error();
      const body:{results:SearchResult[]}=await response.json();setResults(body.results);setSearched(true);
    }catch{setError("公開データを検索できませんでした。")}finally{setBusy(false)}
  }
  return <main className="public-search-page"><section className="card public-search-card">
    <div><span className="eyebrow">PUBLIC SEARCH</span><h2>公開棋譜・コメントを検索</h2><p>検索結果を選ぶと、公開棋譜の盤面と分岐盤を確認できます。</p></div>
    <form onSubmit={search}><div className="form-row"><label htmlFor="public-search">キーワード<input id="public-search" type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="例：終盤、詰み、飛車を切る" maxLength={200}/></label><label htmlFor="public-search-tesu">表示手数<input id="public-search-tesu" type="number" min="0" max="1000" value={tesu} onChange={event=>setTesu(event.target.value)} placeholder="例：30"/></label></div><button disabled={busy||!query.trim()&&!tesu}>{busy?"検索中…":"公開データを検索"}</button></form>
    {error&&<p className="alert" role="alert">{error}</p>}
    {searched&&results.length===0&&<p className="empty">一致する公開データはありません。</p>}
    {results.length>0&&<div className="search-results" aria-live="polite">{results.map(result=>{const targetTesu=result.move_number??(tesu?Number(tesu):null);return <a className="public-search-result" href={`/public/games/${result.game_id}${targetTesu!==null?`?tesu=${targetTesu}`:""}`} key={result.source_type+"-"+result.source_id}><strong>{result.title}</strong><span>{result.event_name??"棋戦名不明"}・総手数 {result.move_count??"不明"}手{targetTesu!==null?"・"+targetTesu+"手目を表示":""}</span><p>{result.text||"公開情報はありません。"}</p><small>{result.source_type==="game"?"公開棋譜":result.source_type==="critical_position"?"重要局面":"匿名コメント"}を開く</small></a>})}</div>}
  </section></main>;
}

function TopPostingTerms(){
  return <main className="top-terms-page"><section className="card top-posting-terms" aria-labelledby="top-posting-terms-title"><span className="eyebrow">POSTING TERMS</span><h2 id="top-posting-terms-title">棋譜投稿規約</h2><p>匿名で解析を申し込む前に、以下の規約をご確認ください。</p><details className="posting-terms"><summary>棋譜投稿規約（全文）を確認する</summary><div><h4>第1条（投稿できる棋譜）</h4><p>投稿者本人が実際に対局し、第三者の権利・利益を侵害せず、本サービスへ投稿する権限を持つ棋譜に限り投稿できます。</p><h4>第2条（プロ公式戦棋譜の投稿禁止）</h4><p>棋士・女流棋士その他プロとして行われた公式戦・棋戦の棋譜は、棋戦、対局日、公開元、入手方法、公開設定および利用許諾の有無を問わず投稿できません。書き写し、形式変換、対局者名・棋戦名の削除や変更、一部の切り出しなど、実質的に指し手順を再現できるものも禁止します。</p><h4>第3条（権利者等の利用条件）</h4><p>本サービスは日本将棋連盟および棋戦主催者の権利・利益を尊重し、プロ公式戦棋譜を一律に禁止します。本規約は権利者の利用許諾を代替しません。</p><h4>第4条（公開設定）</h4><p>棋譜は公開・非公開を選べますが、非公開でも禁止対象は投稿できません。</p><h4>第5条（拒否および削除）</h4><p>禁止対象または権利侵害のおそれがある投稿は、照合等により拒否し、投稿後も公開停止、削除、解析停止、報酬取消等の措置を行うことがあります。</p><h4>第6条（投稿者の責任）</h4><p>投稿者は本人対局・未投稿・規約適合を確認し、虚偽申告や違反により生じた問題へ自己の責任で対応します。</p><h4>第7条（報酬の振込）</h4><p>投稿者は、確定報酬のうち振込可能額が10,000円以上となった場合に、所定の方法で振込を申請できます。</p><h4>第8条（規約の変更）</h4><p>法令、権利者のガイドラインまたはサービス内容に応じて本規約を変更し、サービス上に表示した時点から適用します。</p><a href="https://www.shogi.or.jp/kifuguideline/" target="_blank" rel="noreferrer">日本将棋連盟「棋譜利用のガイドライン」</a></div></details></section></main>;
}
function TopPage({loggedIn,onNavigate,onGoogleLogin,onAnonymousAnalyze,busy,error}:{loggedIn:boolean;onNavigate:(path:string)=>void;onGoogleLogin:(credential:string)=>void;onAnonymousAnalyze:(event:FormEvent<HTMLFormElement>)=>void;busy:boolean;error:string}){
  return <><header className="site-header top-header"><div><span className="eyebrow">KIFU COMMENT LAB</span><h1>棋譜コメント研究所</h1></div>{loggedIn?<button type="button" onClick={()=>onNavigate("/dashboard")}>ダッシュボードへ</button>:<GoogleLoginButton onCredential={onGoogleLogin} compact/>}</header><main className="top-page"><section className="top-hero"><div><span className="eyebrow">対局を、次の一手の力に。</span><h2>形勢が動いた瞬間を、<br/>自分の言葉で振り返る。</h2><p>メールアドレスも名前も不要です。トップページから棋譜を解析し、重要局面へのコメントを匿名で入力できます。</p><div className="button-row"><a className="primary-anchor" href="#anonymous-analysis">今すぐ匿名で解析</a><button type="button" className="link-button" onClick={()=>onNavigate("/service")}>サービスを見る</button></div></div><div className="top-feature card"><span className="eyebrow">HOW IT WORKS</span><ol><li><strong>棋譜を投稿</strong><span>KIF・KI2・CSA・USIに対応</span></li><li><strong>重要局面を解析</strong><span>形勢が動いた瞬間を抽出</span></li><li><strong>匿名で振り返る</strong><span>個人情報なしでコメントを入力</span></li></ol></div></section><section id="anonymous-analysis" className="card anonymous-analysis"><div><span className="eyebrow">ANONYMOUS ANALYSIS</span><h2>トップページで棋譜解析</h2><p>棋譜と対局情報だけで始められます。匿名コメントは、このブラウザの専用セッションにだけ紐づきます。</p></div><form onSubmit={onAnonymousAnalyze}><label>棋譜ファイル（貼り付ける場合は不要）<input name="game_file" type="file" accept=".kif,.ki2,.csa,.txt"/></label><div className="input-separator">または</div><label>棋譜を貼り付け<textarea name="game_text" className="game-text-input" placeholder="KIF・KI2・CSA・USI形式を自動判定します"/></label><div className="form-row"><label>対局日<input name="played_at" type="date" required/></label><label>あなたの手番<select name="user_side"><option value="SENTE">先手</option><option value="GOTE">後手</option></select></label></div><input name="is_public" type="hidden" value="false"/><label className="check"><input name="ownership_confirmed" type="checkbox" value="true" required/>本人対局で、過去に投稿していません。</label><label className="check"><input name="posting_terms_agreed" type="checkbox" value="true" required/><a href="#top-posting-terms-title">棋譜投稿規約</a>を確認し、プロ公式戦棋譜を投稿しないことに同意します。</label>{error&&<p className="alert" role="alert">{error}</p>}<button disabled={busy}>{busy?"匿名セッションを準備中…":"匿名で解析を申し込む"}</button><small className="input-help">ログアウトやブラウザデータの削除後は、匿名の解析結果へ戻れません。</small></form></section></main></>;
}
function ServicePage({loggedIn,onNavigate}:{loggedIn:boolean;onNavigate:(path:string)=>void}){
  return <><header className="site-header"><div><span className="eyebrow">KIFU COMMENT LAB</span><h1>棋譜コメント研究所</h1></div><div className="button-row"><button type="button" className="link-button" onClick={()=>onNavigate("/")}>トップへ</button><button type="button" onClick={()=>onNavigate(loggedIn?"/dashboard":"/login")}>{loggedIn?"ダッシュボードへ":"無料で始める"}</button></div></header><main className="service-page"><section className="service-intro"><span className="eyebrow">ABOUT THE SERVICE</span><h2>対局の振り返りを、<br/>次の一手の力に。</h2><p>棋譜コメント研究所は、あなた自身の将棋棋譜を解析する棋譜解析サイトです。形勢が動いた重要局面を見つけます。AIの答えを見るだけではなく、その局面で何を考えていたかを自分の言葉で残すことで、判断の癖と成長を見える形にします。</p></section><section className="service-gallery" aria-label="サービス画面イメージ"><figure><div className="service-image-wrap"><img src="/service/board-evaluation.png" alt="将棋盤と候補手、評価値の推移を表示した棋譜解析画面"/><span className="service-image-note">画像はイメージ画像です。</span></div><figcaption><span className="eyebrow">GAME ANALYSIS</span><strong>盤面と評価値を、一つの画面で</strong><p>指し手ごとの盤面を再生しながら、形勢の推移とAIの候補手を確認できます。</p></figcaption></figure><figure><div className="service-image-wrap"><img src="/service/skill-estimation.png" alt="推定棋力、棋力推移、学習テーマを表示した棋力診断画面"/><span className="service-image-note">画像はイメージ画像です。</span></div><figcaption><span className="eyebrow">SKILL DIAGNOSIS</span><strong>棋力と次の課題を見える化</strong><p>複数の対局をもとに棋力を推定し、伸ばしたい分野と次の学習テーマを整理します。</p></figcaption></figure></section><section className="service-features"><article className="card"><span>01</span><h3>棋譜をかんたん投稿</h3><p>KIF・KI2・CSA・USI形式に対応。ファイル選択だけでなく、クリップボードからの貼り付けでも解析を申し込めます。</p></article><article className="card"><span>02</span><h3>重要局面を自動抽出</h3><p>形勢が大きく動いた場面を解析し、振り返るべき局面を絞り込みます。盤面再生や評価値の推移も確認できます。</p></article><article className="card"><span>03</span><h3>自分の思考を言語化</h3><p>考えていたこと、比較した候補手、判断の原因を3つの質問で整理。対局時の思考を学びとして蓄積できます。</p></article><article className="card"><span>04</span><h3>棋力と課題を診断</h3><p>複数の棋譜から推定棋力や序盤・中盤・終盤の傾向を表示し、次に勉強するテーマを提案します。</p></article></section><section className="service-flow card"><span className="eyebrow">FLOW</span><h2>ご利用の流れ</h2><ol><li><strong>アカウントを作成</strong><p>メール認証後、すぐに利用できます。</p></li><li><strong>本人対局の棋譜を投稿</strong><p>対局日と自分の手番を選びます。</p></li><li><strong>解析完了後に振り返り</strong><p>重要局面へコメントを入力します。</p></li><li><strong>棋力診断で次の課題を確認</strong><p>対局を重ねるほど推移が蓄積されます。</p></li></ol></section><section className="service-plan"><div><span className="eyebrow">PLAN</span><h2>基本機能は無料で利用できます</h2><p>棋譜投稿、重要局面の振り返り、コメント提出後の評価値確認に対応。AIコメントと詳しい読み筋はAI解説プランで利用できます。</p></div><div className="service-plan-card"><span>AI解説プラン</span><strong>初回1か月無料</strong><small>その後 月額1,000円</small></div></section><section className="service-cta"><h2>次の対局につながる振り返りを、始めましょう。</h2><button type="button" onClick={()=>onNavigate(loggedIn?"/dashboard":"/login")}>{loggedIn?"ダッシュボードを開く":"無料で始める"}</button></section></main></>;
}


const googleClientId="478664202380-mof7pprv83gv1degbi1q1fok3fnnnm3u.apps.googleusercontent.com";

function GoogleLoginButton({onCredential,compact=false}:{onCredential:(credential:string)=>void;compact?:boolean}){
  const containerId="google-login-button";
  useEffect(()=>{
    let attempts=0;
    const render=()=>{
      const googleApi=(window as typeof window & {google?:{accounts:{id:{initialize:(options:{client_id:string;callback:(response:{credential:string})=>void})=>void;renderButton:(element:HTMLElement,options:Record<string,string|number>)=>void}}}}).google;
      const element=document.getElementById(containerId);
      if(!googleApi||!element){
        if(attempts++<50)window.setTimeout(render,100);
        return;
      }
      element.replaceChildren();
      googleApi.accounts.id.initialize({client_id:googleClientId,callback:response=>onCredential(response.credential)});
      googleApi.accounts.id.renderButton(element,{type:"standard",theme:"outline",size:"large",text:"signin_with",shape:"rectangular",width:compact?260:320});
    };
    render();
  },[onCredential,compact]);
  return <div className={compact?"google-login-wrap compact":"google-login-wrap"}><div id={containerId}/>{compact&&<a className="header-login-link" href="/login">ログインページへ</a>}<small>Googleアカウントでログインまたは新規登録できます。</small></div>;
}

function EvaluationChart({frames,currentIndex,userSide,onSelect}:{frames:PlaybackFrame[];currentIndex:number;userSide:"SENTE"|"GOTE";onSelect:(index:number)=>void}){
  const width=640,height=190,padding={top:18,right:18,bottom:30,left:48};
  const values=frames.map(frame=>frame.evaluation);
  const limit=3000;
  const x=(index:number)=>padding.left+(frames.length<=1?0:index/(frames.length-1))*(width-padding.left-padding.right);
  const y=(value:number)=>{const normalized=Math.max(-limit,Math.min(limit,value));return padding.top+(limit-normalized)/(limit*2)*(height-padding.top-padding.bottom)};
  const segments:string[]=[];let segment="";
  values.forEach((value,index)=>{if(value===null){if(segment)segments.push(segment);segment="";return}segment+=(segment?" L ":"M ")+`${x(index)} ${y(value)}`});
  if(segment)segments.push(segment);
  const currentValue=values[currentIndex];
  const label=(value:number)=>value>0?`+${Math.round(value)}`:String(Math.round(value));
  return <div className="evaluation-chart"><div className="evaluation-chart-heading"><strong>評価値の推移</strong><span>＋ {userSide==="SENTE"?"先手（投稿者）":"後手（投稿者）"}優勢　− {userSide==="SENTE"?"後手":"先手"}優勢</span></div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="対局中の評価値推移グラフ" onClick={event=>{const box=event.currentTarget.getBoundingClientRect();const relative=(event.clientX-box.left)/box.width;onSelect(Math.round(Math.max(0,Math.min(1,(relative*width-padding.left)/(width-padding.left-padding.right)))*(frames.length-1)))}}>
    <line className="chart-grid" x1={padding.left} x2={width-padding.right} y1={padding.top} y2={padding.top}/><line className="chart-zero" x1={padding.left} x2={width-padding.right} y1={y(0)} y2={y(0)}/><line className="chart-grid" x1={padding.left} x2={width-padding.right} y1={height-padding.bottom} y2={height-padding.bottom}/>
    <text x={padding.left-7} y={padding.top+4} textAnchor="end">{label(limit)}</text><text x={padding.left-7} y={y(0)+4} textAnchor="end">0</text><text x={padding.left-7} y={height-padding.bottom+4} textAnchor="end">{label(-limit)}</text>
    {segments.map((path,index)=><path className="chart-line" d={path} key={index}/>)}
    <line className="chart-cursor" x1={x(currentIndex)} x2={x(currentIndex)} y1={padding.top} y2={height-padding.bottom}/>{currentValue!==null&&<circle className="chart-point" cx={x(currentIndex)} cy={y(currentValue)} r="5"/>}
    <text x={padding.left} y={height-7}>0手</text><text x={width-padding.right} y={height-7} textAnchor="end">{frames.length-1}手</text>
  </svg><div className="evaluation-chart-current"><span>{frames[currentIndex]?.move_number??currentIndex}手目</span><strong>{currentValue===null?"評価なし":label(currentValue)}</strong></div></div>
}

function BranchEditor({gameId,baseMoveNumber,apiFetch,onError,apiPrefix="/api/games"}:{gameId:number;baseMoveNumber:number;apiFetch:(path:string,init?:RequestInit)=>Promise<Response>;onError:(message:string)=>void;apiPrefix?:string}){
  const [active,setActive]=useState(false),[position,setPosition]=useState<BranchPosition|null>(null);
  const [selected,setSelected]=useState<{kind:"square"|"hand";value:string}|null>(null),[busy,setBusy]=useState(false);
  const [activeBase,setActiveBase]=useState(baseMoveNumber),[analysis,setAnalysis]=useState<BranchAnalysis|null>(null),[analyzing,setAnalyzing]=useState(false);
  const [saved,setSaved]=useState<SavedBranch[]>([]),[saving,setSaving]=useState(false);
  const [boardRotated,setBoardRotated]=useState(false);
  const [branchLine,setBranchLine]=useState<string[]>([]),[selectedBranchId,setSelectedBranchId]=useState<number|null>(null),[deletingBranch,setDeletingBranch]=useState(false);
  useEffect(()=>{setActive(false);setPosition(null);setSelected(null);setActiveBase(baseMoveNumber);setAnalysis(null);setBranchLine([]);setSelectedBranchId(null)},[gameId,baseMoveNumber]);
  useEffect(()=>{void loadSaved()},[gameId]);
  async function load(moves:string[],moveNumber=activeBase){
    setBusy(true);
    try{const response=await apiFetch(`${apiPrefix}/${gameId}/branch-position`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({move_number:moveNumber,moves})});if(!response.ok){onError("分岐局面を作成できませんでした。");return}setActiveBase(moveNumber);setPosition(await response.json());setSelected(null);setAnalysis(null)}
    catch{onError("分岐局面の通信に失敗しました。")}finally{setBusy(false)}
  }
  async function loadSaved(){if(apiPrefix!=="/api/games")return;try{const response=await apiFetch(`/api/games/${gameId}/branches`);if(response.ok)setSaved(await response.json())}catch{/* 分岐作成自体は利用できるため、一覧の取得失敗だけでは操作を妨げない。 */}}
  async function saveBranch(){if(!position?.moves.length||saving)return;setSaving(true);try{const response=await apiFetch(`/api/games/${gameId}/branches`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({move_number:activeBase,moves:position.moves})});if(!response.ok){onError("分岐を保存できませんでした。");return}const item:SavedBranch=await response.json();setSaved(previous=>[...previous,item]);setSelectedBranchId(item.id)}catch{onError("分岐保存の通信に失敗しました。")}finally{setSaving(false)}}
  async function deleteBranch(){if(selectedBranchId===null||deletingBranch||!window.confirm("削除していいですか？"))return;setDeletingBranch(true);try{const response=await apiFetch(`/api/games/${gameId}/branches/${selectedBranchId}`,{method:"DELETE"});if(!response.ok){onError("分岐を削除できませんでした。");return}setSaved(previous=>previous.filter(item=>item.id!==selectedBranchId));setSelectedBranchId(null);setBranchLine([]);setActive(false);setPosition(null)}catch{onError("分岐削除の通信に失敗しました。")}finally{setDeletingBranch(false)}}
  async function analyze(){if(!position||analyzing)return;setAnalyzing(true);try{const response=await apiFetch(`${apiPrefix}/${gameId}/branch-analysis`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({move_number:activeBase,moves:position.moves})});if(!response.ok){let message="分岐局面を解析できませんでした。";try{const body=await response.json();if(typeof body.detail==="string")message=body.detail}catch{}onError(message);return}setAnalysis(await response.json())}catch{onError("分岐解析の通信に失敗しました。")}finally{setAnalyzing(false)}}
  function exploreCandidate(variation:BranchAnalysisVariation){
    const candidateMove=variation.usi_principal_variation[0];
    if(!position||!candidateMove||busy)return;
    const nextMoves=[...position.moves,candidateMove];
    setBranchLine(nextMoves);
    setSelectedBranchId(null);
    void load(nextMoves);
  }
  function chooseMove(candidates:BranchMove[]){
    if(!candidates.length)return;
    let move=candidates[0];
    if(candidates.length>1){const promote=candidates.find(item=>item.promote);const plain=candidates.find(item=>!item.promote);if(promote&&plain)move=window.confirm("成りますか？")?promote:plain}
    const nextMoves=[...(position?.moves??[]),move.usi];setBranchLine(nextMoves);void load(nextMoves);
  }
  function squareClick(square:string,piece:BoardPiece|null){
    if(!position||busy)return;
    if(selected){const candidates=position.legal_moves.filter(move=>move.to_square===square&&(selected.kind==="square"?move.from_square===selected.value:move.drop_piece===selected.value));if(candidates.length){chooseMove(candidates);return}}
    const own=piece?.owner===position.turn;setSelected(own?{kind:"square",value:square}:null);
  }
  const destinations=new Set(position?.legal_moves.filter(move=>selected&&(selected.kind==="square"?move.from_square===selected.value:move.drop_piece===selected.value)).map(move=>move.to_square)??[]);
  const currentBranches=saved.filter(item=>item.base_move_number===baseMoveNumber);
  if(!active)return <div className="branch-launcher"><button type="button" className="branch-start-button" onClick={()=>{setActive(true);setActiveBase(baseMoveNumber);setBranchLine([]);setSelectedBranchId(null);void load([],baseMoveNumber)}}>この局面から分岐を作成</button>{currentBranches.length?<div className="saved-branches"><strong>保存した分岐</strong>{currentBranches.map((item,index)=><button type="button" key={item.id} onClick={()=>{setActive(true);setBranchLine(item.usi_moves);setSelectedBranchId(item.id);void load(item.usi_moves,item.base_move_number)}}>分岐{index+1}</button>)}</div>:null}</div>;
  if(!position)return <div className="branch-editor"><p>{busy?"分岐盤を準備しています…":"分岐盤を読み込めませんでした。"}</p></div>;
  const ownHand=position.board.hands[position.turn];
  return <section className={boardRotated?"branch-editor board-container-rotated":"branch-editor"} aria-label="棋譜分岐作成"><div className="branch-heading"><div><strong>分岐作成</strong><small>{activeBase}手目から・次は{position.turn==="SENTE"?"先手":"後手"}</small></div><div><button type="button" className="board-rotate-button" aria-pressed={boardRotated} onClick={()=>setBoardRotated(value=>!value)}>盤を回転</button>{selectedBranchId!==null&&<button type="button" className="branch-delete-button" aria-label="この分岐を削除" title="この分岐を削除" disabled={deletingBranch} onClick={()=>void deleteBranch()}>{deletingBranch?"…":"×"}</button>}<button type="button" disabled={!position.moves.length||busy} onClick={()=>void load([])}>最初へ</button><button type="button" disabled={!position.moves.length||busy} onClick={()=>void load(position.moves.slice(0,-1))}>前へ</button><button type="button" disabled={position.moves.length>=branchLine.length||busy} onClick={()=>void load(branchLine.slice(0,position.moves.length+1))}>次へ</button><button type="button" disabled={position.moves.length>=branchLine.length||busy} onClick={()=>void load(branchLine)}>最後へ</button><button type="button" onClick={()=>{setActive(false);setPosition(null)}}>閉じる</button></div></div><div className="saved-branches"><strong>保存した分岐</strong>{saved.length?saved.map(item=><button type="button" key={item.id} onClick={()=>{setBranchLine(item.usi_moves);setSelectedBranchId(item.id);void load(item.usi_moves,item.base_move_number)}}>{item.name}</button>):<small>まだありません</small>}</div><p className="input-help">動かす駒をクリックし、色の付いた移動先をクリックしてください。駒取りも同じ操作です。</p><div className="branch-board-area"><div className="branch-hand"><span>手番の持ち駒</span>{ownHand.length?ownHand.map(item=>{const symbolToUsi:Record<string,string>={歩:"P",香:"L",桂:"N",銀:"S",金:"G",角:"B",飛:"R"};const value=symbolToUsi[item.symbol];return <button type="button" className={selected?.kind==="hand"&&selected.value===value?"selected":""} key={item.symbol} onClick={()=>setSelected({kind:"hand",value})}>{item.symbol}{item.count>1?item.count:""}</button>}):<small>なし</small>}</div><div className="board-coordinate-grid"><div className="board-files">{[9,8,7,6,5,4,3,2,1].map(file=><span key={file}>{file}</span>)}</div><div className="shogi-board branch-board">{position.board.squares.flatMap((row,rank)=>row.map((piece,file)=>{const square=`${9-file}${String.fromCharCode(97+rank)}`;return <button type="button" aria-label={`${square}${piece?.symbol??"空"}`} className={`board-square${selected?.kind==="square"&&selected.value===square?" selected":""}${destinations.has(square)?" legal-target":""}`} key={square} onClick={()=>squareClick(square,piece)}>{piece&&<span className={piece.owner==="GOTE"?"gote-piece":""}>{piece.symbol}</span>}</button>}))}</div><div className="board-ranks">{[1,2,3,4,5,6,7,8,9].map(rank=><span key={rank}>{rank}</span>)}</div></div></div><div className="branch-actions"><button type="button" disabled={!position.moves.length||saving} onClick={()=>void saveBranch()}>{saving?"保存中…":"分岐保存"}</button><button type="button" disabled={analyzing} onClick={()=>void analyze()}>{analyzing?"解析中…":"この分岐局面を解析"}</button></div><div className="branch-sequence"><strong>分岐手順</strong>{position.japanese_moves.length?<ol>{position.japanese_moves.map((move,index)=><li key={index}>{move}</li>)}</ol>:<p>まだ指し手がありません。</p>}{position.game_over&&<p className="notice">終局局面です。</p>}</div>{analysis&&<div className="branch-analysis"><h4>分岐局面の解析</h4><p className="evaluation-value">{analysis.mate_in!==null?`詰み ${analysis.mate_in}`:analysis.evaluation??"–"}<small> 勝率 {analysis.win_rate}%</small></p><small>{analysis.engine_name}・{analysis.engine_version}{analysis.evaluation_function?`／${analysis.evaluation_function}`:""}</small>{analysis.variations.map((item,index)=><article key={index}><strong>候補 {index+1}　{item.mate_in!==null?`詰み ${item.mate_in}`:`評価 ${item.evaluation??"–"}`}</strong><p>{item.principal_variation.join(" → ")||"読み筋なし"}</p><button type="button" className="branch-explore-button" disabled={busy||!item.usi_principal_variation.length} onClick={()=>exploreCandidate(item)}>この候補手から続きを探索する</button></article>)}</div>}</section>;
}


function ReadonlyBoard({board,label}:{board:PlaybackFrame["board"];label:string}){
  return <div className="admin-board"><div className="piece-stand"><span>後手の持ち駒</span><strong>{board.hands.GOTE.length?board.hands.GOTE.map(item=>item.symbol+(item.count>1?item.count:"")).join(" "):"なし"}</strong></div><div className="board-coordinate-grid"><div className="board-files">{[9,8,7,6,5,4,3,2,1].map(file=><span key={file}>{file}</span>)}</div><div className="shogi-board" aria-label={label}>{board.squares.flatMap((row,rank)=>row.map((piece,file)=><div className="board-square" key={rank+"-"+file}>{piece&&<span className={piece.owner==="GOTE"?"gote-piece":""}>{piece.symbol}</span>}</div>))}</div><div className="board-ranks">{[1,2,3,4,5,6,7,8,9].map(rank=><span key={rank}>{rank}</span>)}</div></div><div className="piece-stand"><span>先手の持ち駒</span><strong>{board.hands.SENTE.length?board.hands.SENTE.map(item=>item.symbol+(item.count>1?item.count:"")).join(" "):"なし"}</strong></div></div>;
}

function PublicGamePage({gameId,onBack,pathTesu}:{gameId:number;onBack:()=>void;pathTesu?:number}){
  const requestedTesu=Math.max(0,(pathTesu??Number(new URLSearchParams(location.search).get("tesu")??0))||0);
  const [playback,setPlayback]=useState<Playback|null>(null),[index,setIndex]=useState(requestedTesu),[error,setError]=useState("");
  useEffect(()=>{void (async()=>{try{const response=await fetch(`/api/games/public/${gameId}/playback`);if(!response.ok)throw new Error();const body:Playback=await response.json();setPlayback(body);setIndex(Math.min(requestedTesu,body.frames.length-1))}catch{setError("公開棋譜を読み込めませんでした。")}})()},[gameId]);
  const frame=playback?.frames[index]??null;
  return <main className="public-search-page"><section className="card public-search-card">
    <button type="button" className="back-button" onClick={onBack}>← トップページへ</button>
    <span className="eyebrow">PUBLIC GAME</span><h2>{playback?.filename??"公開棋譜"}</h2>
    {error&&<p className="alert" role="alert">{error}</p>}
    {!playback&&!error&&<p>棋譜を読み込んでいます…</p>}
    {playback&&frame&&<><p>{playback.event_name??"棋戦名不明"}<br/>先手 {playback.sente_name??"不明"} ／ 後手 {playback.gote_name??"不明"}</p>
      <ReadonlyBoard board={frame.board} label={`${frame.move_number}手目の公開棋譜盤面`}/>
      <h3>{frame.move_number}手目・{frame.japanese_move}</h3>
      <div className="playback-controls"><button onClick={()=>setIndex(0)} disabled={index===0}>最初</button><button onClick={()=>setIndex(Math.max(0,index-1))} disabled={index===0}>前へ</button><button onClick={()=>setIndex(Math.min(playback.frames.length-1,index+1))} disabled={index===playback.frames.length-1}>次へ</button><button onClick={()=>setIndex(playback.frames.length-1)} disabled={index===playback.frames.length-1}>最後</button></div>
      <input className="move-slider" type="range" min="0" max={playback.frames.length-1} value={index} onChange={event=>setIndex(Number(event.target.value))} aria-label="公開棋譜の再生手数"/>
      <BranchEditor gameId={gameId} baseMoveNumber={frame.move_number} apiFetch={(path,init)=>fetch(path,init)} apiPrefix="/api/games/public" onError={setError}/>
    </>}
  </section></main>;
}

function AdminPanelBase({users,games,error,apiFetch}:{users:AdminUser[];games:AdminGame[];error:string;apiFetch:(path:string,init?:RequestInit)=>Promise<Response>}){
  const [selected,setSelected]=useState<AdminGame|null>(null),[detail,setDetail]=useState<Playback|null>(null),[branches,setBranches]=useState<AdminBranch[]>([]),[index,setIndex]=useState(0),[selectedBranch,setSelectedBranch]=useState<AdminBranch|null>(null),[loading,setLoading]=useState(false),[detailError,setDetailError]=useState("");
  async function openAdminGame(game:AdminGame){setSelected(game);setDetail(null);setBranches([]);setIndex(0);setSelectedBranch(null);setLoading(true);setDetailError("");try{const [playbackResponse,branchesResponse]=await Promise.all([apiFetch("/api/admin/games/"+game.id+"/playback"),apiFetch("/api/admin/games/"+game.id+"/branches")]);if(!playbackResponse.ok||!branchesResponse.ok)throw new Error();setDetail(await playbackResponse.json());setBranches(await branchesResponse.json())}catch{setDetailError("棋譜の盤面を読み込めませんでした。")}finally{setLoading(false)}}
  const frame=detail?.frames[index]??null;
  return <section className="card admin-card"><span className="eyebrow">ADMIN</span><h3>管理画面</h3>{error&&<p className="alert" role="alert">{error}</p>}<div className="admin-list-section"><h4>ユーザー一覧</h4>{users.length===0?<p className="empty">ユーザーはいません。</p>:<div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>ユーザー</th><th>登録日</th><th>棋譜数</th><th>課金状況</th></tr></thead><tbody>{users.map(item=><tr key={item.id}><td><strong>{item.email}</strong><small>#{item.id}{item.is_admin?"・管理者":""}{item.email_verified?"・認証済み":"・未認証"}</small></td><td>{item.created_at.slice(0,10)}</td><td>{item.game_count}</td><td>{item.permanent_access?<span className="admin-plan permanent">永久無料クーポン対象</span>:item.ai_access_active?<span className="admin-plan active">月額プラン有効</span>:<span className="admin-plan inactive">未課金</span>}</td></tr>)}</tbody></table></div>}</div><div className="admin-list-section"><h4>棋譜一覧</h4>{games.length===0?<p className="empty">棋譜はありません。</p>:<div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>棋譜</th><th>対局者</th><th>投稿ユーザー</th><th>対局日</th><th>解析状況</th><th>一致率判定</th><th>公開</th></tr></thead><tbody>{games.map(item=><tr key={item.id} className={selected?.id===item.id?"selected":""}><td><button type="button" className="admin-game-link" onClick={()=>void openAdminGame(item)}><strong>{item.original_filename}</strong><small>#{item.id}・{item.event_name??"棋戦名不明"}・{item.move_count}手</small>{item.professional_level_deletion_candidate&&<span className="admin-delete-candidate">プロレベル削除対象</span>}</button></td><td>先手 {item.sente_name??"不明"}<small>後手 {item.gote_name??"不明"}</small></td><td>{item.user_email}</td><td>{item.played_at}</td><td>{statusLabels[item.analysis_status]??item.analysis_status}<small>重要局面 {item.critical_position_count}件</small></td><td>{item.best_move_match_rate===null?<span className="admin-match-pending">未算出</span>:item.match_rate_analyzed_moves<20?<><strong>{item.best_move_match_rate}%</strong><small>判定対象外（{item.match_rate_analyzed_moves}/20手）</small></>:item.professional_level_deletion_candidate?<><span className="admin-delete-candidate">プロレベル削除対象</span><small>一致率 {item.best_move_match_rate}%・{item.match_rate_analyzed_moves}手</small></>:<><strong>{item.best_move_match_rate}%</strong><small>削除対象外・{item.match_rate_analyzed_moves}手</small></>}</td><td>{item.is_public?"公開":"非公開"}</td></tr>)}</tbody></table></div>}</div>{selected&&<div className="admin-game-detail"><div className="section-title"><div><h4>{selected.original_filename} の確認</h4><p>先手 {selected.sente_name??"不明"} ／ 後手 {selected.gote_name??"不明"}<br/>対局日 {selected.played_at}・投稿 {selected.user_email}</p>{selected.professional_level_deletion_candidate?<p className="alert admin-professional-warning"><strong>プロレベル削除対象</strong><br/>AI第1候補一致率 {selected.best_move_match_rate}%（解析対象 {selected.match_rate_analyzed_moves}手）</p>:<p className="input-help">AI第1候補一致率 {selected.best_move_match_rate===null?"未算出":selected.best_move_match_rate+"%"}（解析対象 {selected.match_rate_analyzed_moves}手）</p>}</div><button type="button" onClick={()=>{setSelected(null);setDetail(null)}}>閉じる</button></div>{loading&&<p>盤面を読み込んでいます…</p>}{detailError&&<p className="alert" role="alert">{detailError}</p>}{frame&&detail&&<div className="admin-playback-layout"><div><ReadonlyBoard board={frame.board} label={frame.move_number+"手目の管理者確認盤面"}/><div className="playback-controls"><button type="button" onClick={()=>setIndex(0)} disabled={index===0}>最初</button><button type="button" onClick={()=>setIndex(Math.max(0,index-1))} disabled={index===0}>前へ</button><button type="button" onClick={()=>setIndex(Math.min(detail.frames.length-1,index+1))} disabled={index===detail.frames.length-1}>次へ</button><button type="button" onClick={()=>setIndex(detail.frames.length-1)} disabled={index===detail.frames.length-1}>最後</button></div><input className="move-slider" type="range" min="0" max={detail.frames.length-1} value={index} onChange={event=>setIndex(Number(event.target.value))} aria-label="管理者用再生手数"/></div><aside><h4>{frame.move_number}手目・{frame.japanese_move}</h4><p>次の手番：{frame.board.turn==="SENTE"?"先手":"後手"}</p>{frame.is_critical&&<span className="critical-badge">重要局面</span>}<h4>保存済み分岐</h4>{branches.length===0?<p className="empty">保存済み分岐はありません。</p>:<div className="admin-branch-list">{branches.map(branch=><button type="button" key={branch.id} className={selectedBranch?.id===branch.id?"active":""} onClick={()=>setSelectedBranch(branch)}>{branch.name}（{branch.base_move_number}手目から）</button>)}</div>}{selectedBranch&&<div className="admin-branch-detail"><ReadonlyBoard board={selectedBranch.board} label={selectedBranch.name+"の最終盤面"}/><strong>{selectedBranch.name}の指し手</strong><ol>{selectedBranch.japanese_moves.map((move,moveIndex)=><li key={moveIndex}>{move}</li>)}</ol></div>}</aside></div>}</div>}</section>;
}

function LegacyAdminPanel(props:{users:AdminUser[];games:AdminGame[];error:string;apiFetch:(path:string,init?:RequestInit)=>Promise<Response>}){
  const [visibility,setVisibility]=useState<Record<number,boolean>>({});
  const [busyId,setBusyId]=useState<number|null>(null);
  const [visibilityError,setVisibilityError]=useState("");
  async function updateVisibility(game:AdminGame,isPublic:boolean){
    setBusyId(game.id);setVisibilityError("");
    try{
      const response=await props.apiFetch(`/api/admin/games/${game.id}/visibility`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({is_public:isPublic})});
      if(!response.ok)throw new Error();
      setVisibility(current=>({...current,[game.id]:isPublic}));
    }catch{setVisibilityError("公開設定を変更できませんでした。")}finally{setBusyId(null)}
  }
  return <><AdminPanelBase {...props}/><section className="card admin-card"><span className="eyebrow">ADMIN VISIBILITY</span><h3>棋譜の公開設定</h3>{visibilityError&&<p className="alert" role="alert">{visibilityError}</p>}{props.games.length===0?<p className="empty">棋譜はありません。</p>:<div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>棋譜</th><th>投稿ユーザー</th><th>公開</th></tr></thead><tbody>{props.games.map(game=>{const checked=visibility[game.id]??game.is_public;return <tr key={game.id}><td><strong>{game.original_filename}</strong><small>#{game.id}</small></td><td>{game.user_email}</td><td><label className="check"><input type="checkbox" checked={checked} disabled={busyId===game.id} onChange={event=>void updateVisibility(game,event.target.checked)}/>{busyId===game.id?"変更中…":checked?"公開":"非公開"}</label></td></tr>})}</tbody></table></div>}</section></>;
}

function AdminPanel(props:{users:AdminUser[];games:AdminGame[];error:string;apiFetch:(path:string,init?:RequestInit)=>Promise<Response>}){
  const [visibility,setVisibility]=useState<Record<number,boolean>>({});
  const [busyId,setBusyId]=useState<number|null>(null);
  const [visibilityError,setVisibilityError]=useState("");
  async function updateVisibility(game:AdminGame,isPublic:boolean){
    setBusyId(game.id);setVisibilityError("");
    try{
      const response=await props.apiFetch(`/api/admin/games/${game.id}/visibility`,{
        method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({is_public:isPublic}),
      });
      if(!response.ok)throw new Error();
      setVisibility(current=>({...current,[game.id]:isPublic}));
    }catch{setVisibilityError("公開設定を変更できませんでした。")}finally{setBusyId(null)}
  }
  return <>
    <AdminPanelBase {...props}/>
    <section className="card admin-card">
      <span className="eyebrow">ADMIN VISIBILITY</span><h3>棋譜の公開設定</h3>
      {visibilityError&&<p className="alert" role="alert">{visibilityError}</p>}
      {props.games.length===0?<p className="empty">棋譜はありません。</p>:<div className="admin-table-wrap"><table className="admin-table">
        <thead><tr><th>棋譜</th><th>対局者</th><th>投稿ユーザー</th><th>公開</th></tr></thead>
        <tbody>{props.games.map(game=>{const checked=visibility[game.id]??game.is_public;return <tr key={game.id}>
          <td><strong>{game.original_filename}</strong><small>#{game.id}</small></td>
          <td>先手 {game.sente_name??"不明"}<small>後手 {game.gote_name??"不明"}</small></td>
          <td>{game.user_email}</td>
          <td><label className="check"><input type="checkbox" checked={checked} disabled={busyId===game.id} onChange={event=>void updateVisibility(game,event.target.checked)}/>{busyId===game.id?"変更中…":checked?"公開":"非公開"}</label></td>
        </tr>})}</tbody>
      </table></div>}
    </section>
  </>;
}

export default function App(){
  const [path,setPath]=useState(()=>normalizePath(window.location.pathname));
  const [accessToken,setAccessToken]=useState(()=>localStorage.getItem("access_token")??"");
  const [refreshToken,setRefreshToken]=useState(()=>localStorage.getItem("refresh_token")??"");
  const [user,setUser]=useState<User|null>(null);
  const [games,setGames]=useState<Game[]>([]);
  const [rewards,setRewards]=useState<Rewards>(emptyRewards);
  const [aiSubscription,setAiSubscription]=useState<AiSubscription>({active:false,trial_available:true,permanent_access:false,status:"NONE",current_period_end:null,monthly_price_yen:1000,trial_days:30,test_toggle_available:false});
  const [selectedGame,setSelectedGame]=useState<Game|null>(null);
  const [skillEstimationGameId,setSkillEstimationGameId]=useState<number|null>(()=>{const match=window.location.pathname.match(/^\/games\/(\d+)\/skill-estimation$/);return match?Number(match[1]):null});
  const [positions,setPositions]=useState<Position[]>([]);
  const [playback,setPlayback]=useState<Playback|null>(null);
  const [playbackIndex,setPlaybackIndex]=useState(0);
  const [variationIndex,setVariationIndex]=useState(0);
  const [visibleVariationMoves,setVisibleVariationMoves]=useState(5);
  const [showTestEvaluation,setShowTestEvaluation]=useState(false);
  const [mainBoardRotated,setMainBoardRotated]=useState(false);
  const [submission,setSubmission]=useState<Submission|null>(null);
  const [answers,setAnswers]=useState<Record<string,string>>({});
  const [aiComments,setAiComments]=useState<AiComment[]>([]);
  const [aiCommentDrafts,setAiCommentDrafts]=useState<Record<number,string>>({});
  const [searchQuery,setSearchQuery]=useState("");
  const [searchResults,setSearchResults]=useState<SearchResult[]>([]);
  const [searching,setSearching]=useState(false);
  const [reviews,setReviews]=useState<ReviewItem[]>([]);
  const [adminUsers,setAdminUsers]=useState<AdminUser[]>([]);
  const [adminGames,setAdminGames]=useState<AdminGame[]>([]);
  const [adminListError,setAdminListError]=useState("");
  const [error,setError]=useState("");
  const [notice,setNotice]=useState(()=>new URLSearchParams(location.search).get("verified")?"メール認証が完了しました。ログインしてください。":"");
  const [busy,setBusy]=useState(false);
  const [reanalyzingGameId,setReanalyzingGameId]=useState<number|null>(null);
  const [uploadError,setUploadError]=useState("");
  const [registering,setRegistering]=useState(false);
  const [commentBusy,setCommentBusy]=useState(false);
  const [positionAdding,setPositionAdding]=useState(false);
  const [commentFeedback,setCommentFeedback]=useState<{kind:"error"|"success";text:string}|null>(null);
  const [menuOpen,setMenuOpen]=useState(false);
  const showCodeEntry=path==="/code";
  const [codeBusy,setCodeBusy]=useState(false);
  const [codeFeedback,setCodeFeedback]=useState<{kind:"error"|"success";text:string}|null>(null);

  const navigate=useCallback((nextPath:string,replace=false)=>{const normalized=normalizePath(nextPath);window.history[replace?"replaceState":"pushState"]({},"",normalized);setPath(normalized);window.scrollTo({top:0,behavior:"smooth"})},[]);
  useEffect(()=>{const onPopState=()=>setPath(normalizePath(window.location.pathname));window.addEventListener("popstate",onPopState);return()=>window.removeEventListener("popstate",onPopState)},[]);
  useEffect(()=>{
    const seo=seoByPath[path];
    const publicPage=Boolean(seo);
    const title=seo?.title??"棋譜コメント研究所";
    const description=seo?.description??"棋譜コメント研究所のユーザー専用ページです。";
    const canonical=siteUrl+(path==="/"?"/":path);
    document.title=title;
    setMeta('meta[name="description"]',"content",description);
    setMeta('meta[name="robots"]',"content",publicPage?"index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1":"noindex,nofollow");
    setMeta('meta[property="og:title"]',"content",title);
    setMeta('meta[property="og:description"]',"content",description);
    setMeta('meta[property="og:url"]',"content",canonical);
    setMeta('meta[name="twitter:title"]',"content",title);
    setMeta('meta[name="twitter:description"]',"content",description);
    const canonicalLink=document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if(canonicalLink)canonicalLink.href=canonical;
  },[path]);

  function saveTokens(access:string,refresh:string){
    localStorage.setItem("access_token",access); localStorage.setItem("refresh_token",refresh);
    setAccessToken(access); setRefreshToken(refresh);
  }
  function logout(){
    localStorage.removeItem("access_token"); localStorage.removeItem("refresh_token");
    setAccessToken(""); setRefreshToken(""); setUser(null); setGames([]); setSelectedGame(null); setPlayback(null);navigate("/");
  }
  async function refreshAccess(){
    if(!refreshToken)return null;
    const response=await fetch("/api/auth/refresh",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({refresh_token:refreshToken})});
    if(!response.ok){logout();return null}
    const tokens=await response.json(); saveTokens(tokens.access_token,tokens.refresh_token); return tokens.access_token as string;
  }
  async function apiFetch(path:string,init:RequestInit={},retry=true):Promise<Response>{
    const headers=new Headers(init.headers); if(accessToken)headers.set("Authorization","Bearer "+accessToken);
    const response=await fetch(path,{...init,headers});
    if(response.status===401&&retry){const token=await refreshAccess();if(token){headers.set("Authorization","Bearer "+token);return fetch(path,{...init,headers})}}
    return response;
  }
  async function responseError(response:Response){
    try{const body=await response.json();return typeof body.detail==="string"?body.detail:JSON.stringify(body.detail)}
    catch{return "HTTP "+response.status}
  }
  async function retryAfterProfessionalWarning(response:Response,data:FormData,send:()=>Promise<Response>):Promise<Response>{
    if(response.status!==409)return response;
    const body=await response.clone().json().catch(()=>null);
    if(body?.detail?.code!=="PROFESSIONAL_NAME_CONFIRMATION_REQUIRED")return response;
    const names=Array.isArray(body.detail.matched_names)?body.detail.matched_names.join("、"):"プロ棋士名";
    const confirmed=window.confirm(`${body.detail.message}\n\n一致した名前: ${names}\n\nプロ公式戦棋譜は登録できません。`);
    if(!confirmed)return new Response(JSON.stringify({detail:"プロ棋士名との一致があるため、登録を中止しました。"}),{status:409,headers:{"Content-Type":"application/json"}});
    data.set("professional_name_confirmed","true");
    return send();
  }
  async function loadDashboard(){
    if(!accessToken)return;
    try{
      const [me,gamesResponse,rewardResponse,subscriptionResponse]=await Promise.all([apiFetch("/api/auth/me"),apiFetch("/api/games"),apiFetch("/api/rewards/summary"),apiFetch("/api/ai-access/status")]);
      if(!me.ok||!gamesResponse.ok||!rewardResponse.ok||!subscriptionResponse.ok)throw new Error("ダッシュボードを読み込めませんでした。");
      const current=await me.json();const loadedGames:Game[]=await gamesResponse.json();setUser(current);setGames(loadedGames);setSelectedGame(previous=>previous?loadedGames.find(game=>game.id===previous.id)??previous:null);setRewards(await rewardResponse.json());setAiSubscription(await subscriptionResponse.json());
      if(current.is_admin&&current.mfa_enabled){
        const [reviewsResponse,usersResponse,adminGamesResponse]=await Promise.all([apiFetch("/api/admin/reviews"),apiFetch("/api/admin/users"),apiFetch("/api/admin/games")]);
        if(reviewsResponse.ok&&usersResponse.ok&&adminGamesResponse.ok){setReviews(await reviewsResponse.json());setAdminUsers(await usersResponse.json());setAdminGames(await adminGamesResponse.json());setAdminListError("")}
        else setAdminListError("管理用一覧を読み込めませんでした。");
      }
      setError("");
    }catch(reason){setError(reason instanceof Error?reason.message:"通信に失敗しました。")}
  }
  useEffect(()=>{if(!accessToken||path.includes("/skill-estimation"))return;void loadDashboard();const timer=window.setInterval(()=>void loadDashboard(),3000);return()=>window.clearInterval(timer)},[accessToken,path]);

  async function register(event:FormEvent<HTMLFormElement>){
    event.preventDefault();setRegistering(true);setError("");
    const form=event.currentTarget;const data=new FormData(form);const email=String(data.get("email"));const password=String(data.get("password"));
    try{
      const response=await fetch("/api/auth/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})});
      if(!response.ok){setError(await responseError(response));navigate("/login");return}
      const result:{message:string}=await response.json();
      form.reset();setNotice(result.message+" メール内のリンクを開いてからログインしてください。");
    }catch{setError("通信に失敗しました。時間をおいて再度お試しください。")}finally{setRegistering(false)}
  }
  async function resendVerification(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const form=event.currentTarget;const data=new FormData(form);
    const response=await fetch("/api/auth/resend-verification",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:data.get("email")})});
    if(!response.ok)return setError(await responseError(response));
    const result:{message:string}=await response.json();form.reset();setNotice(result.message);setError("");
  }
  async function requestPasswordReset(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const form=event.currentTarget;const data=new FormData(form);setError("");
    try{const response=await fetch("/api/auth/request-password-reset",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:data.get("email")})});if(!response.ok){setError(await responseError(response));navigate("/login");return}const result:{message:string}=await response.json();form.reset();setNotice(result.message)}
    catch{setError("通信に失敗しました。時間をおいて再度お試しください。")}
  }
  async function resetPassword(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const form=event.currentTarget;const data=new FormData(form);const password=String(data.get("password"));const confirmation=String(data.get("password_confirmation"));setError("");
    if(password!==confirmation){setError("確認用パスワードが一致しません。");return}
    const token=new URLSearchParams(window.location.search).get("token")??"";
    try{const response=await fetch("/api/auth/reset-password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token,password})});if(!response.ok){setError(await responseError(response));navigate("/login");return}const result:{message:string}=await response.json();form.reset();setNotice(result.message);navigate("/login",true)}
    catch{setError("通信に失敗しました。時間をおいて再度お試しください。")}
  }
  async function login(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const data=new FormData(event.currentTarget);
    const response=await fetch("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:data.get("email"),password:data.get("password"),mfa_code:data.get("mfa_code")||null})});
    if(!response.ok)return setError(await responseError(response));const tokens=await response.json();saveTokens(tokens.access_token,tokens.refresh_token);setError("");navigate("/dashboard");
  }
  async function googleLogin(credential:string){
    setError("");
    try{
      const response=await fetch("/api/auth/google",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({credential})});
      if(!response.ok){setError(await responseError(response));navigate("/login");return}
      const tokens=await response.json();saveTokens(tokens.access_token,tokens.refresh_token);navigate("/dashboard");
    }catch{setError("Googleログインの通信に失敗しました。時間をおいて再度お試しください。")}
  }
  async function anonymousAnalyze(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const form=event.currentTarget;const data=new FormData(form);
    const file=data.get("game_file");const hasFile=file instanceof File&&file.size>0;
    const hasText=String(data.get("game_text")??"").trim().length>0;
    if(hasFile===hasText){setUploadError("棋譜ファイルまたは貼り付け棋譜のどちらか一方を入力してください。");return}
    if(!window.confirm("提出した匿名コメントは、管理者の審査で承認された後に限り、AI改善のための学習データとして利用されます。同意して解析を始めますか？"))return;
    setBusy(true);setUploadError("");setError("");
    try{
      let token=accessToken;
      if(!token){
        const sessionResponse=await fetch("/api/auth/anonymous",{method:"POST"});
        if(!sessionResponse.ok){setUploadError(await responseError(sessionResponse));return}
        const tokens=await sessionResponse.json();token=tokens.access_token;saveTokens(tokens.access_token,tokens.refresh_token);
      }
      let response=await fetch("/api/games",{method:"POST",headers:{Authorization:"Bearer "+token},body:data});
      response=await retryAfterProfessionalWarning(response,data,()=>fetch("/api/games",{method:"POST",headers:{Authorization:"Bearer "+token},body:data}));
      if(!response.ok){setUploadError(await responseError(response));return}
      const game:Game=await response.json();form.reset();setNotice("匿名で棋譜を受け付けました。解析後、重要局面へコメントできます。");navigate("/games/"+game.id);
    }catch{setUploadError("通信に失敗しました。時間をおいて再度お試しください。")}finally{setBusy(false)}
  }
  async function redeemAccessCode(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const form=event.currentTarget;const data=new FormData(form);setCodeBusy(true);setCodeFeedback(null);
    try{
      const response=await apiFetch("/api/ai-access/redeem-code",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code:data.get("access_code")})});
      if(!response.ok){setCodeFeedback({kind:"error",text:await responseError(response)});return}
      const result:{permanent_access:boolean;message:string}=await response.json();form.reset();setCodeFeedback({kind:"success",text:result.message});await loadDashboard();if(selectedGame)await openGame(selectedGame);
    }catch{setCodeFeedback({kind:"error",text:"通信に失敗しました。時間をおいて再度お試しください。"})}finally{setCodeBusy(false)}
  }

  async function startAiSubscription(){
    const response=await apiFetch("/api/ai-access/checkout",{method:"POST"});
    if(!response.ok)return setError(await responseError(response));
    const result:{checkout_url:string}=await response.json();window.location.assign(result.checkout_url);
  }
  async function toggleTestSubscription(){
    const response=await apiFetch("/api/ai-access/test-toggle",{method:"POST"});
    if(!response.ok)return setError(await responseError(response));
    await loadDashboard();if(selectedGame)await openGame(selectedGame);setNotice("検証用の月額1,000円課金状態を切り替えました。");
  }
  async function manageAiSubscription(){
    const response=await apiFetch("/api/ai-access/portal",{method:"POST"});
    if(!response.ok)return setError(await responseError(response));
    const result:{portal_url:string}=await response.json();window.location.assign(result.portal_url);
  }
  async function saveBankAccount(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const form=event.currentTarget;const data=new FormData(form);
    const payload={bank_code:data.get("bank_code"),branch_code:data.get("branch_code"),account_type:data.get("account_type"),account_number:data.get("account_number"),account_holder:data.get("account_holder")};
    const response=await apiFetch("/api/rewards/bank-account",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!response.ok)return setError(await responseError(response));setNotice("振込口座を登録しました。");setError("");
  }
  async function requestPayout(){
    const response=await apiFetch("/api/rewards/payouts",{method:"POST"});
    if(!response.ok)return setError(await responseError(response));const result=await response.json();setNotice(yen.format(result.amount_yen)+"の振込を申請しました。");setError("");await loadDashboard();
  }
  async function downloadPayoutCsv(){
    const response=await apiFetch("/api/rewards/payouts.csv");if(!response.ok)return setError(await responseError(response));
    const url=URL.createObjectURL(await response.blob());const anchor=document.createElement("a");anchor.href=url;anchor.download="payouts.csv";anchor.click();URL.revokeObjectURL(url);
  }
  async function downloadAndroidApp(){
    const response=await apiFetch("/api/downloads/android");
    if(!response.ok)return setError(await responseError(response));
    const url=URL.createObjectURL(await response.blob());const anchor=document.createElement("a");anchor.href=url;anchor.download="kifu-comment-lab.apk";document.body.appendChild(anchor);anchor.click();anchor.remove();URL.revokeObjectURL(url);
  }
  async function upload(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    const form=event.currentTarget;const data=new FormData(form);
    const file=data.get("game_file");const hasFile=file instanceof File&&file.size>0;
    const hasText=String(data.get("game_text")??"").trim().length>0;
    if(hasFile===hasText){setUploadError("棋譜ファイルまたは貼り付け棋譜のどちらか一方を入力してください。");return}
    setBusy(true);setUploadError("");setError("");setNotice("");
    try{
      let response=await apiFetch("/api/games",{method:"POST",body:data});
      response=await retryAfterProfessionalWarning(response,data,()=>apiFetch("/api/games",{method:"POST",body:data}));
      if(!response.ok){setUploadError(await responseError(response));return}
      form.reset();setNotice("棋譜を受け付けました。");await loadDashboard();
    }catch{setUploadError("通信に失敗しました。時間をおいて再度お試しください。")}finally{setBusy(false)}
  }

  async function deleteGame(game:Game){
    if(!window.confirm(`「${game.original_filename}」を削除しますか？\n解析結果や下書きも削除され、元に戻せません。`))return;
    const response=await apiFetch("/api/games/"+game.id,{method:"DELETE"});
    if(!response.ok){setError(await responseError(response));navigate("/login");return}
    if(selectedGame?.id===game.id){setSelectedGame(null);setPlayback(null);setPlaybackIndex(0);setShowTestEvaluation(false);setPositions([]);setSubmission(null);setAnswers({})}
    setNotice("棋譜を削除しました。");setError("");await loadDashboard();
  }

  async function updateVisibility(game:Game,isPublic:boolean){
    const response=await apiFetch("/api/games/"+game.id+"/visibility",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({is_public:isPublic})});
    if(!response.ok){setError(await responseError(response));navigate("/login");return}
    const updated:Game=await response.json();
    setGames(current=>current.map(item=>item.id===updated.id?updated:item));
    setSelectedGame(current=>current?.id===updated.id?updated:current);
    setNotice(isPublic?"棋譜を公開に変更しました。":"棋譜を非公開に変更しました。");setError("");
  }

  async function reanalyzeGame(game:Game){
    if(reanalyzingGameId!==null||!window.confirm("この棋譜を再解析しますか？解析結果と棋力推定は作り直されます。"))return;
    setReanalyzingGameId(game.id);setError("");setNotice("");
    try{
      const response=await apiFetch("/api/games/"+game.id+"/reanalyze",{method:"POST"});
      if(!response.ok){setError(await responseError(response));navigate("/login");return}
      const updated:Game=await response.json();setSelectedGame(updated);setGames(games.map(item=>item.id===updated.id?updated:item));setNotice("再解析を受け付けました。完了後に棋力推定できます。");
    }catch{setError("再解析の受付に失敗しました。時間をおいて再度お試しください。")}finally{setReanalyzingGameId(null)}
  }

  async function openGame(game:Game){
    setSelectedGame(game);const base="/api/games/"+game.id;
    const ownGame=game.owner_id===user?.id;
    const [pResponse,playbackResponse,cResponse,aiResponse]=await Promise.all([apiFetch(base+"/critical-positions"),apiFetch(base+"/playback"),ownGame?apiFetch(base+"/comments"):Promise.resolve(null),ownGame?apiFetch(base+"/ai-comments"):Promise.resolve(null)]);
    if(!pResponse.ok||!playbackResponse.ok||ownGame&&!cResponse?.ok)return setError("棋譜と重要局面を読み込めませんでした。");
    const loadedPositions=await pResponse.json();const loadedSubmission=cResponse?await cResponse.json():null;const loadedPlayback=await playbackResponse.json();
    setPositions(ownGame?loadedPositions:[]);setSubmission(loadedSubmission);setPlayback(loadedPlayback);setPlaybackIndex(loadedPlayback.frames.length>1?1:0);setShowTestEvaluation(loadedPlayback.test_evaluation_toggle_available);
    const next:Record<string,string>={};for(const answer of loadedSubmission?.answers??[])next[answerKey(answer.critical_position_id,answer.question_number)]=answer.answer_text;setAnswers(next);
    if(aiResponse?.ok){const loadedAi=await aiResponse.json();setAiComments(loadedAi);setAiCommentDrafts(Object.fromEntries(loadedAi.map((item:AiComment)=>[item.id,item.current_text])))}else{setAiComments([]);setAiCommentDrafts({})}
  }

  async function saveAiComment(comment:AiComment){
    if(!selectedGame)return;const text=aiCommentDrafts[comment.id]??comment.current_text;const response=await apiFetch("/api/games/"+selectedGame.id+"/ai-comments/"+comment.id,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({text})});
    if(!response.ok){setError(await responseError(response));navigate("/login");return}const updated=await response.json();setAiComments(aiComments.map(item=>item.id===updated.id?updated:item));setNotice("AIコメントの修正を学習データとして保存しました。");
  }

  async function runSearch(event:FormEvent<HTMLFormElement>){
    event.preventDefault();const query=searchQuery.trim();if(!query)return;setSearching(true);setError("");
    try{const response=await apiFetch("/api/search?q="+encodeURIComponent(query));if(!response.ok){setError(await responseError(response));navigate("/login");return}const body:{results:SearchResult[]}=await response.json();setSearchResults(body.results)}
    catch{setError("検索に失敗しました。時間をおいて再度お試しください。")}finally{setSearching(false)}
  }

  async function openSearchResult(result:SearchResult){
    const game=games.find(item=>item.id===result.game_id);if(!game)return;await openGame(game);if(result.move_number!==null)setPlaybackIndex(result.move_number);
  }

  async function commentAtCurrentPosition(){
    if(!selectedGame||!currentFrame||currentFrame.move_number<1||positionAdding)return;
    setPositionAdding(true);setError("");
    try{
      const response=await apiFetch("/api/games/"+selectedGame.id+"/comment-position/"+currentFrame.move_number,{method:"POST"});
      if(!response.ok){setError(await responseError(response));navigate("/login");return}
      const position:Position=await response.json();
      setPositions(previous=>previous.some(item=>item.id===position.id)?previous:[...previous,position].sort((a,b)=>a.move_number-b.move_number));
      window.setTimeout(()=>{const target=document.getElementById("comment-position-"+position.id);target?.scrollIntoView({behavior:"smooth",block:"start"});target?.querySelector("textarea")?.focus()},0);
    }catch{setError("コメント局面を追加できませんでした。")}finally{setPositionAdding(false)}
  }

  function answerList():Answer[]{return positions.flatMap(position=>questions.map((_,index)=>({critical_position_id:position.id,question_number:index+1,answer_text:answers[answerKey(position.id,index+1)]??""})))}
  async function saveDraft(){
    if(!selectedGame||commentBusy)return false;setCommentBusy(true);setCommentFeedback(null);
    try{
      const response=await apiFetch("/api/games/"+selectedGame.id+"/comments/draft",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({answers:answerList()})});
      if(!response.ok){const message=await responseError(response);setCommentFeedback({kind:"error",text:message});return false}
      setSubmission(await response.json());setCommentFeedback({kind:"success",text:"下書きを保存しました。"});return true;
    }catch{setCommentFeedback({kind:"error",text:"通信に失敗しました。時間をおいて再度お試しください。"});return false}finally{setCommentBusy(false)}
  }
  async function submitComments(){
    if(!selectedGame||commentBusy)return;
    if(answerList().every(answer=>!answer.answer_text.trim())){setCommentFeedback({kind:"error",text:"コメントを1つ以上入力してから提出してください。"});return}
    setCommentBusy(true);setCommentFeedback(null);
    try{
      const draftResponse=await apiFetch("/api/games/"+selectedGame.id+"/comments/draft",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({answers:answerList()})});
      if(!draftResponse.ok){setCommentFeedback({kind:"error",text:await responseError(draftResponse)});return}
      setSubmission(await draftResponse.json());
      const response=await apiFetch("/api/games/"+selectedGame.id+"/comments/submit",{method:"POST"});
      if(!response.ok){setCommentFeedback({kind:"error",text:await responseError(response)});return}
      setCommentFeedback({kind:"success",text:"コメントを提出しました。"});await openGame(selectedGame);
    }catch{setCommentFeedback({kind:"error",text:"通信に失敗しました。時間をおいて再度お試しください。"})}finally{setCommentBusy(false)}
  }
  async function review(id:number,status:string){
    const reason=window.prompt("審査理由を入力してください。");if(!reason)return;
    const tagText=window.prompt("品質タグをカンマ区切りで入力してください。","")??"";
    const quality_tags=tagText.split(",").map(tag=>tag.trim()).filter(Boolean);
    const response=await apiFetch("/api/admin/reviews/"+id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,reason,quality_tags})});
    if(!response.ok)setError(await responseError(response));else await loadDashboard();
  }

  const yen=new Intl.NumberFormat("ja-JP",{style:"currency",currency:"JPY"});
  const currentFrame=playback?.frames[playbackIndex]??null;
  const selectedVariation=currentFrame?.variations?.[variationIndex]??null;
  const pathParts=path.split("/");
  const routedGameId=pathParts[1]==="games"&&/^\d+$/.test(pathParts[2]??"")?Number(pathParts[2]):null;
  useEffect(()=>{if(!accessToken||routedGameId===null||pathParts[3]==="skill-estimation"||!games.length)return;const game=games.find(item=>item.id===routedGameId);if(game&&selectedGame?.id!==game.id)void openGame(game)},[accessToken,games,path]);
  useEffect(()=>{if(pathParts[3]!=="skill-estimation")return;setSkillEstimationGameId(routedGameId)},[path]);
  useEffect(()=>{setVariationIndex(0);setVisibleVariationMoves(5)},[playbackIndex,playback?.game_id]);
  if(path==="/")return <><ShogiHomeButton onActivate={()=>window.scrollTo({top:0,behavior:"smooth"})}/><HeroShogiPieces/><TopPage loggedIn={Boolean(accessToken)} onNavigate={navigate} onGoogleLogin={googleLogin} onAnonymousAnalyze={anonymousAnalyze} busy={busy} error={uploadError}/><TopPostingTerms/><PublicSearch/></>;
  if(path==="/service")return <ServicePage loggedIn={Boolean(accessToken)} onNavigate={navigate}/>;
  const publicGameMatch=path.match(/^\/public\/games\/(\d+)(?:&tesu=(\d+))?$/);
  if(publicGameMatch)return <PublicGamePage gameId={Number(publicGameMatch[1])} pathTesu={publicGameMatch[2]?Number(publicGameMatch[2]):undefined} onBack={()=>navigate("/")}/>;
  if(path==="/reset-password")return <main className="auth-page"><button type="button" className="back-button" onClick={()=>navigate("/login")}>← ログインへ戻る</button><section className="card reset-password-card"><h1>パスワード再設定</h1>{error&&<p className="alert">{error}</p>}<p>新しいパスワードを入力してください。</p><form onSubmit={resetPassword}><PasswordField id="reset-password" label="新しいパスワード（12文字以上）" autoComplete="new-password" minLength={12}/><PasswordField id="reset-password-confirmation" name="password_confirmation" label="新しいパスワード（確認）" autoComplete="new-password" minLength={12}/><button type="submit">パスワードを変更する</button></form></section></main>;
  if(!accessToken)return <main className="auth-page"><button type="button" className="back-button" onClick={()=>navigate("/")}>← トップページへ</button><h1>棋譜コメント研究所</h1>{error&&<p className="alert">{error}</p>}{notice&&<p className="notice">{notice}</p>}<div className="auth-grid">
    <section className="card"><h2>ログイン</h2><form onSubmit={login}><label>メール<input name="email" type="email" autoComplete="email" required/></label><PasswordField id="login-password" label="パスワード" autoComplete="current-password"/><label>MFAコード（管理者としてログインする場合）<input name="mfa_code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6}/></label><small className="input-help">未入力の場合は、管理者アカウントでも一般ユーザーとしてログインします。</small><button>ログイン</button></form><div className="auth-divider"><span>または</span></div><GoogleLoginButton onCredential={googleLogin}/><hr/><h3>パスワードを忘れた方</h3><form onSubmit={requestPasswordReset}><label>登録メール<input name="email" type="email" autoComplete="email" required/></label><button type="submit" className="link-button">再設定メールを送る</button></form></section>
    <section className="card"><h2>新規登録</h2><form onSubmit={register}><label>メール<input name="email" type="email" autoComplete="email" required/></label><PasswordField id="register-password" label="パスワード（12文字以上）" autoComplete="new-password" minLength={12}/><button disabled={registering}>{registering?"送信中…":"確認メールを送る"}</button></form><hr/><h3>確認メールを再送</h3><form onSubmit={resendVerification}><label>登録メール<input name="email" type="email" autoComplete="email" required/></label><button>再送する</button></form></section>
  </div></main>;

  if(skillEstimationGameId!==null)return <SkillEstimationPage apiFetch={apiFetch} gameId={skillEstimationGameId} onBack={()=>{navigate("/games/"+skillEstimationGameId);setSkillEstimationGameId(null)}}/>;
  return <><header className="site-header"><div><span className="eyebrow">KIFU COMMENT LAB</span><h1>棋譜コメント研究所</h1></div><div className="header-actions"><div className="button-row"><span>{user?.email??"読込中"}</span>{aiSubscription.test_toggle_available&&<button className="link-button subscription-toggle" onClick={()=>void toggleTestSubscription()}>1,000円課金 {aiSubscription.active?"ON":"OFF"}</button>}<button className="link-button" onClick={logout}>ログアウト</button></div><div className="header-menu"><button type="button" className="menu-trigger" aria-haspopup="menu" aria-expanded={menuOpen} onClick={()=>setMenuOpen(open=>!open)}><span aria-hidden="true">☰</span> メニュー</button>{menuOpen&&<div className="menu-popover" role="menu"><button type="button" role="menuitem" onClick={()=>{navigate("/code");setMenuOpen(false)}}>コードを入力</button></div>}</div></div></header><main>
    <ShogiHomeButton onActivate={()=>navigate("/")}/>
    {path==="/code"?<section className="code-entry-page" aria-labelledby="code-entry-title"><button type="button" className="back-button" onClick={()=>navigate("/dashboard")}>← ダッシュボードに戻る</button><div className="card code-entry-card"><span className="eyebrow">ENTER CODE</span><h2 id="code-entry-title">コードを入力</h2><p>お持ちのコードを入力してください。</p>{aiSubscription.permanent_access?<p className="notice">永久無料プランが有効です。評価値とAI解説プランをご利用いただけます。</p>:<form onSubmit={redeemAccessCode}><label htmlFor="access-code">コード<input id="access-code" name="access_code" type="text" placeholder="コードを入力" autoComplete="off" required maxLength={100}/></label><button type="submit" disabled={codeBusy}>{codeBusy?"確認中…":"コードを確認する"}</button></form>}{codeFeedback&&<p className={codeFeedback.kind==="error"?"alert code-feedback":"notice code-feedback"} role={codeFeedback.kind==="error"?"alert":"status"}>{codeFeedback.text}</p>}</div></section>:<>
    {error&&<p className="alert">{error}</p>}{notice&&<p className="notice">{notice}</p>}
    {user?.android_apk_download_allowed&&<section className="card"><span className="eyebrow">ANDROID APP</span><h3>Androidアプリ</h3><p>スマートフォンへインストールするAPKをダウンロードできます。</p><button type="button" onClick={()=>void downloadAndroidApp()}>Androidアプリをダウンロード</button><small className="input-help">ダウンロード後、Androidの案内に従ってインストールしてください。</small></section>}
    <section className="card search-card"><span className="eyebrow">WEAVIATE SEARCH</span><h3>棋譜・局面・コメントを検索</h3><form className="search-form" onSubmit={runSearch}><label htmlFor="global-search">検索語</label><div className="search-input-row"><input id="global-search" type="search" value={searchQuery} onChange={event=>setSearchQuery(event.target.value)} placeholder="例：終盤の逆転、飛車を切った局面" maxLength={200}/><button disabled={searching||!searchQuery.trim()}>{searching?"検索中…":"検索"}</button></div></form>{searchResults.length>0?<div className="search-results">{searchResults.map(result=><button type="button" className="search-result" key={result.source_type+"-"+result.source_id} onClick={()=>void openSearchResult(result)}><strong>{result.title}</strong><span>{result.event_name??"棋戦名不明"}{result.move_number!==null?"・"+result.move_number+"手目":""}</span><p>{result.text}</p><small>{result.backend==="weaviate"?"Weaviate検索":"DB検索"}</small></button>)}</div>:searchQuery&&!searching&&<p className="empty">該当するデータはありません。</p>}</section>
    <section className="hero"><div><p className="eyebrow">対局を、次の一手の力に。</p><h2>形勢が動いた瞬間を<br/>自分の言葉で振り返る。</h2></div><div className="reward-panel"><span>確定報酬</span><strong>{yen.format(rewards.fixed_yen)}</strong><small>承認済み {rewards.approved_games} 棋譜</small></div></section>
    <section className="stats"><article><span>コメント待ち</span><strong>{games.filter(g=>g.analysis_status==="COMMENT_REQUIRED").length}</strong><small>棋譜</small></article><article><span>保留報酬</span><strong>{yen.format(rewards.pending_yen)}</strong><small>上限確認中</small></article><article><span>振込可能額</span><strong>{yen.format(rewards.payout_available_yen)}</strong><small>最低 {yen.format(rewards.minimum_payout_yen)}</small></article></section>
    <section className="card"><span className="eyebrow">AI PLAN</span><h3>AI解説プラン</h3>{aiSubscription.active?<><p className="notice">{aiSubscription.permanent_access?"永久無料プランが有効です":"月額プラン契約中"}{!aiSubscription.permanent_access&&aiSubscription.current_period_end?"・有効期限 "+aiSubscription.current_period_end.slice(0,10):""}</p>{!isNativeAndroid&&!aiSubscription.permanent_access&&!aiSubscription.test_toggle_available&&<button onClick={()=>void manageAiSubscription()}>契約内容・解約を管理</button>}</>:<>{isNativeAndroid?<p className="notice">Androidアプリでは、現在お持ちのAI解説プランを利用できます。新規のお申し込みはWeb版をご利用ください。</p>:<><p>評価値はコメント提出後に無料で表示されます。AIコメントと読み筋は{aiSubscription.trial_available?"初回1か月無料、その後は":""}月額{yen.format(aiSubscription.monthly_price_yen)}です。</p><button onClick={()=>void startAiSubscription()}>{aiSubscription.trial_available?"1か月無料で試す":"AI解説プランを申し込む"}</button></>}</>}</section>
    {rewards.rewards_enabled&&<section className="card"><span className="eyebrow">PAYOUT</span><h3>振込口座と申請</h3><form onSubmit={saveBankAccount}><div className="form-row"><label>銀行コード<input name="bank_code" inputMode="numeric" pattern="[0-9]{4}" maxLength={4} required/></label><label>支店コード<input name="branch_code" inputMode="numeric" pattern="[0-9]{3}" maxLength={3} required/></label></div><div className="form-row"><label>口座種別<select name="account_type"><option value="ORDINARY">普通</option><option value="CURRENT">当座</option></select></label><label>口座番号<input name="account_number" inputMode="numeric" pattern="[0-9]{7}" maxLength={7} required/></label></div><label>口座名義<input name="account_holder" maxLength={100} required/></label><div className="button-row"><button>口座を保存</button><button type="button" disabled={rewards.payout_available_yen===0} onClick={()=>void requestPayout()}>振込を申請</button></div></form>{user?.is_admin&&user.mfa_enabled&&<button onClick={()=>void downloadPayoutCsv()}>振込CSVを出力</button>}</section>}
    <div className="content-grid"><section className="card"><span className="eyebrow">UPLOAD</span><h3>棋譜を解析する</h3><form onSubmit={upload}><label>棋譜ファイル（貼り付ける場合は不要）<input name="game_file" type="file" accept=".kif,.ki2,.csa,.txt"/></label><div className="input-separator">または</div><label>クリップボードから貼り付け<textarea name="game_text" className="game-text-input" placeholder="KIF・KI2・CSA・USI形式を自動判定します"/></label><small className="input-help">ファイルか貼り付けのどちらか一方を入力してください。</small>{uploadError&&<p className="alert upload-error" role="alert">{uploadError}</p>}<div className="form-row"><label>対局日<input name="played_at" type="date" required/></label><label>あなたの手番<select name="user_side"><option value="SENTE">先手</option><option value="GOTE">後手</option></select></label></div><label>公開設定<select name="is_public" defaultValue="false"><option value="false">非公開（自分だけ）</option><option value="true">公開</option></select></label><small className="input-help">初期設定は非公開です。公開を選ぶと、今後公開棋譜一覧の対象になります。</small><details className="posting-terms"><summary>棋譜投稿規約（全文）を確認する</summary><div><h4>第1条（投稿できる棋譜）</h4><p>投稿者本人が実際に対局し、第三者の権利・利益を侵害せず、本サービスへ投稿する権限を持つ棋譜に限り投稿できます。</p><h4>第2条（プロ公式戦棋譜の投稿禁止）</h4><p>棋士・女流棋士その他プロとして行われた公式戦・棋戦の棋譜は、棋戦、対局日、公開元、入手方法、公開設定および利用許諾の有無を問わず投稿できません。書き写し、形式変換、対局者名・棋戦名の削除や変更、一部の切り出しなど、実質的に指し手順を再現できるものも禁止します。</p><h4>第3条（権利者等の利用条件）</h4><p>本サービスは日本将棋連盟および棋戦主催者の権利・利益を尊重し、プロ公式戦棋譜を一律に禁止します。本規約は権利者の利用許諾を代替しません。</p><h4>第4条（公開設定）</h4><p>棋譜は公開・非公開を選べますが、非公開でも禁止対象は投稿できません。</p><h4>第5条（拒否および削除）</h4><p>禁止対象または権利侵害のおそれがある投稿は、照合等により拒否し、投稿後も公開停止、削除、解析停止、報酬取消等の措置を行うことがあります。</p><h4>第6条（投稿者の責任）</h4><p>投稿者は本人対局・未投稿・規約適合を確認し、虚偽申告や違反により生じた問題へ自己の責任で対応します。</p><h4>第7条（報酬の振込）</h4><p>投稿者は、確定報酬のうち振込可能額が10,000円以上となった場合に、所定の方法で振込を申請できます。</p><h4>第8条（規約の変更）</h4><p>法令、権利者のガイドラインまたはサービス内容に応じて本規約を変更し、サービス上に表示した時点から適用します。</p><a href="https://www.shogi.or.jp/kifuguideline/" target="_blank" rel="noreferrer">日本将棋連盟「棋譜利用のガイドライン」</a></div></details><label className="check"><input name="ownership_confirmed" type="checkbox" value="true" required/>本人対局で、過去に投稿していません。</label><label className="check"><input name="posting_terms_agreed" type="checkbox" value="true" required/>棋譜投稿規約を確認し、プロ公式戦棋譜を投稿しないことに同意します。</label><button disabled={busy}>{busy?"受付中…":"解析を申し込む"}</button></form></section>
      <section className="card"><span className="eyebrow">RECENT GAMES</span><h3>{user?.global_game_viewer?"全ユーザーの棋譜":"最近の棋譜"}</h3><div className="game-list">{games.length===0&&<p className="empty">棋譜はまだありません。</p>}{games.map(game=><div className="game-list-row" key={game.id}><button className="game-row game-button" onClick={()=>{navigate("/games/"+game.id);void openGame(game)}}><div className="move-icon">{game.critical_position_count||"–"}</div><div><strong>{game.original_filename}</strong>{user?.global_game_viewer&&<small>所有者: {game.owner_email??"不明"}</small>}<small>{game.event_name??"棋戦名不明"}・先手 {game.sente_name??"不明"} / 後手 {game.gote_name??"不明"}</small><small>{game.played_at}・投稿者は{game.user_side==="SENTE"?"先手":"後手"}・{game.is_public?"公開":"非公開"}</small></div><span className={"status status-"+game.analysis_status.toLowerCase()}>{statusLabels[game.analysis_status]??game.analysis_status}</span></button>{game.owner_id===user?.id&&<button type="button" className="delete-game-button" aria-label={`${game.original_filename}を削除`} onClick={()=>void deleteGame(game)}>削除</button>}</div>)}
</div></section></div>
    {selectedGame&&playback&&currentFrame&&<section className="card playback-card"><div className="section-title"><div><span className="eyebrow">GAME PLAYER</span><h3>棋譜再生</h3><p className="game-metadata">{playback.event_name??"棋戦名不明"}<br/>先手 {playback.sente_name??"不明"} / 後手 {playback.gote_name??"不明"}</p><label>公開設定<select value={String(selectedGame.is_public)} onChange={event=>void updateVisibility(selectedGame,event.target.value==="true")}><option value="false">非公開（自分だけ）</option><option value="true">公開</option></select></label></div><div className="playback-heading-actions"><strong>{currentFrame.move_number}手目・{currentFrame.japanese_move}</strong><button type="button" className="reanalyze-button" disabled={reanalyzingGameId===selectedGame.id||selectedGame.analysis_status==="QUEUED"||selectedGame.analysis_status==="ANALYZING"} onClick={()=>void reanalyzeGame(selectedGame)}>{reanalyzingGameId===selectedGame.id?"受付中…":"再解析"}</button><button type="button" disabled={selectedGame.analysis_status!=="COMMENT_REQUIRED"} onClick={()=>{navigate("/games/"+selectedGame.id+"/skill-estimation");setSkillEstimationGameId(selectedGame.id)}}>棋力推定</button>{selectedGame.analysis_status!=="COMMENT_REQUIRED"&&<small>棋譜解析完了後に棋力推定できます</small>}</div></div><div className="playback-layout"><div className={mainBoardRotated?"board-area board-container-rotated":"board-area"}><button type="button" className="board-rotate-button" aria-pressed={mainBoardRotated} onClick={()=>setMainBoardRotated(value=>!value)}>盤を回転</button><div className="main-board-area-inner"><div className="piece-stand"><span>後手の持ち駒</span><strong>{currentFrame.board.hands.GOTE.length?currentFrame.board.hands.GOTE.map(item=>item.symbol+(item.count>1?item.count:"")).join(" "):"なし"}</strong></div><div className="board-coordinate-grid"><div className="board-files">{[9,8,7,6,5,4,3,2,1].map(file=><span key={file}>{file}</span>)}</div><div className="shogi-board" aria-label={`${currentFrame.move_number}手目の盤面`}>{currentFrame.board.squares.flatMap((row,rank)=>row.map((piece,file)=><div className="board-square" key={`${rank}-${file}`}>{piece&&<span className={piece.owner==="GOTE"?"gote-piece":""}>{piece.symbol}</span>}</div>))}</div><div className="board-ranks">{[1,2,3,4,5,6,7,8,9].map(rank=><span key={rank}>{rank}</span>)}</div></div><div className="piece-stand"><span>先手の持ち駒</span><strong>{currentFrame.board.hands.SENTE.length?currentFrame.board.hands.SENTE.map(item=>item.symbol+(item.count>1?item.count:"")).join(" "):"なし"}</strong></div></div>{(playback.submitted||playback.test_evaluation_toggle_available&&showTestEvaluation)?<EvaluationChart frames={playback.frames} currentIndex={playbackIndex} userSide={playback.user_side} onSelect={setPlaybackIndex}/>:<div className="evaluation-chart-locked">評価値の推移はコメント提出後に表示されます。</div>}<div className="playback-controls"><button type="button" onClick={()=>setPlaybackIndex(0)} disabled={playbackIndex===0}>最初</button><button type="button" onClick={()=>setPlaybackIndex(Math.max(0,playbackIndex-1))} disabled={playbackIndex===0}>前へ</button><button type="button" onClick={()=>setPlaybackIndex(Math.min(playback.frames.length-1,playbackIndex+1))} disabled={playbackIndex===playback.frames.length-1}>次へ</button><button type="button" onClick={()=>setPlaybackIndex(playback.frames.length-1)} disabled={playbackIndex===playback.frames.length-1}>最後</button></div><input className="move-slider" type="range" min="0" max={playback.frames.length-1} value={playbackIndex} onChange={event=>setPlaybackIndex(Number(event.target.value))} aria-label="再生手数"/></div><aside className="playback-info"><div className="turn-indicator">次の手番：{currentFrame.board.turn==="SENTE"?"先手":"後手"}</div>{currentFrame.engine_name&&<p className="engine-identity"><strong>{currentFrame.engine_name==="YaneuraOu"?"やねうら王":currentFrame.engine_name}</strong>{currentFrame.engine_version&&<>・{currentFrame.engine_version}</>}{currentFrame.evaluation_function&&<>／評価関数 {currentFrame.evaluation_function==="Suisho5"?"水匠5":currentFrame.evaluation_function}</>}</p>}{currentFrame.is_critical&&<span className="critical-badge">重要局面</span>}<div className="evaluation-heading"><h4>評価値（{playback.user_side==="SENTE"?"先手":"後手"}・投稿者視点）</h4>{playback.test_evaluation_toggle_available&&<button type="button" className="evaluation-toggle" onClick={()=>setShowTestEvaluation(!showTestEvaluation)}>{showTestEvaluation?"評価値を隠す":"評価値を表示"}</button>}</div>{(playback.submitted||playback.test_evaluation_toggle_available&&showTestEvaluation)?<p className="evaluation-value">{currentFrame.evaluation??"–"}{currentFrame.win_rate!==null&&<small> 勝率 {currentFrame.win_rate}%</small>}</p>:<p className="empty">{playback.test_evaluation_toggle_available?"「評価値を表示」を押すと確認できます。":"コメント提出後に表示されます。"}</p>}
<BranchEditor gameId={selectedGame.id} baseMoveNumber={currentFrame.move_number} apiFetch={apiFetch} onError={setError}/><h4>読み筋・分岐（5候補）</h4>{currentFrame.variations?.length&&selectedVariation?<div className="engine-variations"><div className="variation-tabs" role="tablist" aria-label="予測分岐">{currentFrame.variations.map((variation,index)=><button type="button" role="tab" aria-selected={variationIndex===index} className={variationIndex===index?"active":""} key={index} onClick={()=>{setVariationIndex(index);setVisibleVariationMoves(5)}}>候補 {index+1}<small>評価 {variation.mate_in!==null?"詰み "+variation.mate_in:variation.evaluation??"–"}</small></button>)}</div><article><strong>候補 {variationIndex+1}の{Math.min(visibleVariationMoves,selectedVariation.principal_variation.length)}手先までの予測</strong><ol className="variation-list">{selectedVariation.principal_variation.slice(0,visibleVariationMoves).map((move,moveIndex)=><li key={move+"-"+moveIndex}>{move}</li>)}</ol>{visibleVariationMoves<selectedVariation.principal_variation.length&&<button type="button" className="variation-more-button" onClick={()=>setVisibleVariationMoves(count=>count+5)}>もっと見る</button>}</article></div>:<p className="empty">{playback.ai_visible?"この手の読み筋はありません。":"AIプラン契約後に表示されます。"}</p>}{currentFrame.selection_reason&&<p>{currentFrame.selection_reason}</p>}<button type="button" className="comment-position-button" disabled={currentFrame.move_number<1||Boolean(submission?.submitted_at)||positionAdding} onClick={()=>void commentAtCurrentPosition()}>{positionAdding?"追加中…":submission?.submitted_at?"コメント提出済み":currentFrame.move_number<1?"1手目以降を選択してください":"指定局面でコメントする"}</button>{submission?.submitted_at&&<p className="input-help">承認・審査対象の内容を保護するため、提出済み棋譜には局面を追加できません。</p>}<h4>コメント</h4>{currentFrame.comments.length?currentFrame.comments.map(comment=><div className="playback-comment" key={comment.question_number}><strong>{comment.question_number}. {comment.question}</strong><p>{comment.answer||"未入力"}</p></div>):<p className="empty">この手には重要局面コメントがありません。</p>}<div className="critical-jumps"><strong>重要局面へ移動</strong>{playback.frames.filter(frame=>frame.is_critical).map(frame=><button type="button" key={frame.move_number} onClick={()=>setPlaybackIndex(frame.move_number)}>{frame.move_number}手目</button>)}</div></aside></div></section>}
    {selectedGame&&<section className="card reflection"><span className="eyebrow">REFLECTION</span><h3>{selectedGame.original_filename} の重要局面</h3>{positions.length===0&&<p>解析中、または重要局面がありません。</p>}{positions.map(position=><article className="position-card" id={"comment-position-"+position.id} key={position.id}><h4>{position.move_number}手目・{position.japanese_move}</h4>{questions.map((question,index)=><label key={question}>{index+1}. {question}<textarea value={answers[answerKey(position.id,index+1)]??""} onChange={event=>setAnswers({...answers,[answerKey(position.id,index+1)]:event.target.value})} disabled={Boolean(submission?.submitted_at)}/></label>)}{position.engine_explanation_visible&&<div className="engine-result"><strong>評価: {position.evaluation_before} → {position.evaluation_after}</strong>{position.selection_reason&&<p>{position.selection_reason}</p>}{position.principal_variation&&<p><strong>読み筋:</strong> {position.principal_variation.length?position.principal_variation.join(" → "):"読み筋はありません。"}</p>}</div>}</article>)}{positions.length>0&&!submission?.submitted_at&&<><div className="button-row"><button type="button" disabled={commentBusy} onClick={()=>void saveDraft()}>{commentBusy?"処理中…":"下書き保存"}</button><button type="button" disabled={commentBusy} onClick={()=>void submitComments()}>{commentBusy?"提出中…":"一括提出"}</button></div>{commentFeedback&&<p className={commentFeedback.kind==="error"?"alert comment-feedback":"notice comment-feedback"} role={commentFeedback.kind==="error"?"alert":"status"}>{commentFeedback.text}</p>}</>}{submission?.submitted_at&&<p className="notice">提出済み・{submission.review_status}</p>}{submission?.submitted_at&&!aiSubscription.active&&<p className="alert">AIコメントと読み筋は月額プラン登録後に表示されます。</p>}{submission?.submitted_at&&aiSubscription.active&&<div className="ai-comment-section"><h3>収集コメントから生成したAIコメント</h3><p className="input-help">修正内容は同じ手数の次回生成に反映されます。</p>{aiComments.length?aiComments.map(comment=><article className="ai-comment-editor" key={comment.id}><strong>{comment.move_number}手目</strong><textarea value={aiCommentDrafts[comment.id]??comment.current_text} onChange={event=>setAiCommentDrafts({...aiCommentDrafts,[comment.id]:event.target.value})}/><button type="button" onClick={()=>void saveAiComment(comment)}>修正を保存・学習</button></article>):<p className="empty">AIコメントを生成中です。</p>}</div>}</section>}
    {user?.is_admin&&user.mfa_enabled&&<><AdminPanel users={adminUsers} games={adminGames} error={adminListError} apiFetch={apiFetch}/><section className="card admin-card"><span className="eyebrow">ADMIN REVIEW</span><h3>審査対象</h3>{reviews.length===0&&<p className="empty">審査対象はありません。</p>}{reviews.map(item=><article key={item.id} className="review-row"><span>投稿 #{item.id}・棋譜 #{item.game_id}・{item.status}</span>{item.snapshot?.positions.map(position=><div key={position.id}><strong>{position.move_number}手目・{position.move}</strong>{[1,2,3].map(questionNumber=>{const answer=item.snapshot?.answers.find(candidate=>candidate.critical_position_id===position.id&&candidate.question_number===questionNumber);return <p key={questionNumber}>{questionNumber}. {answer?.answer_text.trim()||"無回答"}</p>})}</div>)}{item.status==="UNDER_REVIEW"&&<div className="button-row"><button onClick={()=>void review(item.id,"APPROVED")}>承認</button><button onClick={()=>void review(item.id,"CHANGES_REQUESTED")}>差し戻し</button><button onClick={()=>void review(item.id,"REJECTED")}>却下</button></div>}</article>)}</section></>}
  </>}</main></>;
}
