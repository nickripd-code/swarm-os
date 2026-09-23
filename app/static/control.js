import {newState,applyEvent,layoutTree,terminal,alertFromEvent,resultMetaText,missionMode,costHudView,formatUsd,tokenTotal,parseCommand,resolveCommand,killRoutePresent,recordEvent,projectEvents,replayView,stepReplay,clampReplayIndex,isReplayLive,missionModelChip} from "./state.mjs";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g,c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const label = role => String(role||"Agent").replaceAll("_"," ");
const statusName = status => ({created:"Ready",running:"Thinking",completed:"Done",blocked:"Blocked",failed:"Failed",stopped:"Stopped",pending:"Queued",paused:"Paused",waiting:"Waiting"}[status] || status);
const symbol = status => ({created:"·",running:"",completed:"✓",blocked:"?",failed:"!",stopped:"■"}[status] || "·");
const colors = ["#c6b4ef","#edbd9e","#aed8cf","#e6cd90","#b5cbe3","#dfb9ca"];
let state=newState(), selected=null, ws=null, generation=0, retry=null, zoom=1, graph=null, frame=0, previewTimer=null, health=null, hudTick=null, notifyArmed=false, killAvailable=false;
let eventLog=[], replayCursor=-1, replayLive=true, replayTimer=null, sourceMission=null;
const elements=new Map();
const bot = color => '<span class="bot" style="--agent-color:'+color+'" aria-hidden="true"><span class="ear ear-left"></span><span class="ear ear-right"></span><span class="visor"><i></i><i></i><b class="mouth"></b></span></span>';
function colorFor(a) {if(!a.parent_id)return colors[0];let n=0;for(const c of a.role)n=(n*31+c.charCodeAt(0))>>>0;return colors[1+n%(colors.length-1)];}
function showNotice(message) {$("notice").textContent=message;$("notice").hidden=!message;}
function setCommandStatus(message,kind){
  const el=$("commandBarStatus");
  if(!el)return;
  el.textContent=message||"";
  el.hidden=!message;
  if(kind)el.dataset.kind=kind;else delete el.dataset.kind;
  if(kind==="error"&&message)showNotice(message);
  else if(kind==="ok")showNotice("");
}
function haltPreviewLocally(){
  if(!state.preview)return;
  clearTimeout(previewTimer);
  for(const a of state.agents.values())a.status="stopped";
  if(state.mission){
    state.mission.status="stopped";
    state.mission.result={reason:"Preview halted"};
  }
  pushAlert({level:"warning",title:"Execution stopped",detail:"Preview halted",event_type:"mission.stopped"});
  schedule();
}
function connection(text,cls="") {$("connection").className="connection "+cls;$("connection").innerHTML="<i></i>"+esc(text);}
function formatElapsed(ms){
  if(!Number.isFinite(ms)||ms<0)ms=0;
  const s=Math.floor(ms/1000), m=Math.floor(s/60), h=Math.floor(m/60);
  if(h)return h+"h "+(m%60)+"m";
  if(m)return m+"m "+(s%60)+"s";
  return s+"s";
}
function renderHud(){
  const mission=state.mission, status=mission?.status||"idle", mode=missionMode(state);
  if($("objectiveText"))$("objectiveText").textContent=mission?.goal||"Awaiting a mission.";
  if($("missionMode")){
    $("missionMode").textContent=String(mode).replaceAll("_"," ").toUpperCase();
    $("missionMode").className="hud-chip mode "+mode;
  }
  if($("missionStatus")){
    $("missionStatus").textContent=status.toUpperCase();
    $("missionStatus").className="hud-chip status "+status;
  }
  if($("hudAgents"))$("hudAgents").textContent=state.agents.size;
  if($("hudTasks"))$("hudTasks").textContent=[...state.tasks.values()].filter(t=>t.status==="completed").length;
  const cost=costHudView(state.usage);
  if($("hudTokens"))$("hudTokens").textContent=tokenTotal(state.usage).toLocaleString();
  if($("hudSpend"))$("hudSpend").textContent=cost.spendLabel;
  if($("costHudNote"))$("costHudNote").textContent=cost.note;
  if($("costHudTokens"))$("costHudTokens").textContent=cost.tokensLabel;
  if($("costHudSpend"))$("costHudSpend").textContent=cost.spendLabel;
  if($("costHudBudget")){
    $("costHudBudget").textContent=cost.remainingLabel
      ? cost.remainingLabel+" remaining of "+cost.budgetLabel
      : cost.budgetLabel;
  }
  if($("costHud"))$("costHud").dataset.known=cost.known?"true":"false";
  if($("hudElapsed")){
    const view=replayView(eventLog,replayCursor,{preview:state.preview,mission:sourceMission||mission});
    if(!replayLive&&!state.preview&&view.elapsedMs!=null){
      $("hudElapsed").textContent=formatElapsed(view.elapsedMs);
    }else{
      const start=mission?.created_at?new Date(mission.created_at).getTime():NaN;
      $("hudElapsed").textContent=Number.isFinite(start)?formatElapsed(Date.now()-start):"—";
    }
  }
  if($("replayChip")){
    $("replayChip").hidden=state.preview||!mission;
    $("replayChip").textContent=state.preview?"PREVIEW":(replayLive?"LIVE":"REPLAY");
    $("replayChip").className="hud-chip mode "+(state.preview?"preview":replayLive?"replay-live":"replay");
  }
  if($("missionModel")){
    const chip=missionModelChip(state);
    $("missionModel").hidden=!chip.visible;
    $("missionModel").textContent=chip.visible?chip.label:"";
    if(chip.visible){
      $("missionModel").title=chip.model;
      $("missionModel").setAttribute("aria-label","Model "+chip.model);
    }else{
      $("missionModel").removeAttribute("title");
      $("missionModel").removeAttribute("aria-label");
    }
  }
  const running=!!mission&&!terminal.has(status)&&replayLive&&!state.preview;
  if(running&&!hudTick)hudTick=setInterval(renderHud,1000);
  if(!running&&hudTick){clearInterval(hudTick);hudTick=null;}
}
function clearAlerts(){if($("alerts"))$("alerts").replaceChildren();}
function pushAlert(alert){
  if(!alert||!$("alerts"))return;
  const stack=$("alerts");
  for(const el of [...stack.children]){
    if(el.dataset.type===alert.event_type&&el.dataset.detail===(alert.detail||""))el.remove();
  }
  const item=document.createElement("article");
  item.className="alert-card "+(alert.level||"info");
  item.dataset.type=alert.event_type||"";
  item.dataset.detail=alert.detail||"";
  const klass=alert.failure_class?'<span class="alert-class">'+esc(alert.failure_class)+"</span>":"";
  item.innerHTML="<header><strong>"+esc(alert.title)+"</strong>"+klass+'<button type="button" class="alert-dismiss" aria-label="Dismiss">Ã—</button></header>'+(alert.detail?"<p>"+esc(alert.detail)+"</p>":"");
  item.querySelector(".alert-dismiss").onclick=ev=>{ev.stopPropagation();item.remove();};
  item.onclick=()=>{const panel=$("resultPanel");if(panel&&!panel.hidden)panel.scrollIntoView({behavior:"smooth",block:"nearest"});};
  stack.prepend(item);
  while(stack.children.length>5)stack.lastElementChild.remove();
  if(alert.level==="success")setTimeout(()=>item.remove(),8000);
  maybeNotify(alert);
}
function considerAlert(e,liveFrom){
  const alert=alertFromEvent(e);
  if(!alert)return;
  if(e.created_at){
    const created=new Date(e.created_at).getTime();
    if(Number.isFinite(created)&&created<liveFrom-2000)return;
  }
  pushAlert(alert);
}
function maybeNotify(alert){
  if(!notifyArmed||typeof Notification==="undefined"||Notification.permission!=="granted"||!document.hidden)return;
  try{
    const body=[alert.failure_class,alert.detail].filter(Boolean).join(" · ").slice(0,140);
    const n=new Notification(alert.title,{body,tag:"swarm-"+(alert.event_type||"alert")});
    n.onclick=()=>{window.focus();n.close();};
  }catch{}
}
function armNotifications(){
  notifyArmed=true;
  if(typeof Notification!=="undefined"&&Notification.permission==="default")Promise.resolve(Notification.requestPermission()).catch(()=>{});
}
function schedule(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;render();});}
function render(){
  const mission=state.mission, status=mission?.status||"idle";
  renderHud();
  $("modeLabel").textContent=state.preview?"PREVIEW":(!replayLive?"REPLAY":status.toUpperCase());
  $("modeLabel").className="mode-tag "+(state.preview?"preview":(!replayLive?"replay":status));
  $("agentCount").textContent=state.agents.size;
  $("taskCount").textContent=[...state.tasks.values()].filter(t=>t.status==="completed").length;
  $("tokenCount").textContent=tokenTotal(state.usage).toLocaleString();
  $("eventCount").textContent=state.seen.size+" events";
  $("emptyMap").hidden=state.agents.size>0;
  $("launch").disabled=!!mission&&!terminal.has(status)&&!state.preview;
  $("launch").innerHTML=$("launch").disabled?'Mission running <span>⌁</span>':'Launch mission <span>↗</span>';
  $("missionCaption").textContent=state.preview?"Interactive preview · no models or tools are running":(!replayLive?"Historical replay · recorded events only":mission?.goal||"One mission. As many minds as it needs.");
  if(state.preview)connection("Preview");
  else if(!replayLive)connection("Replay");
  else if(terminal.has(status))connection("Mission "+status,status==="completed"?"live":"disconnected");
  graph=layoutTree(state.agents,Math.max(650,$("mapViewport").clientWidth/zoom));
  $("world").style.width=graph.width+"px";$("world").style.height=graph.height+"px";
  $("world").style.transform="scale("+zoom+")";
  $("mapSpacer").style.width=graph.width*zoom+"px";$("mapSpacer").style.height=graph.height*zoom+"px";
  const svg=$("connections");
  let paths='<defs><marker id="messageArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#7de6ff"/></marker></defs>';
  for(const a of state.agents.values()){
    const pos=graph.positions.get(a.id), parent=graph.positions.get(a.parent_id);
    if(parent&&pos&&parent.depth<pos.depth){
      const x=parent.x+105,y=parent.y+149,tx=pos.x+105,ty=pos.y-24,mid=(y+ty)/2;
      paths+='<path class="branch-line '+(a.status==="running"?'active ':'')+(selected===a.id?'selected':'')+'" d="M '+x+' '+y+' C '+x+' '+mid+', '+tx+' '+mid+', '+tx+' '+ty+'"/><circle class="branch-joint" cx="'+x+'" cy="'+y+'" r="3"/>';
    }
  }
  const recent=(!state.replay&&replayLive)?state.events.filter(e=>e.event_type==='agent.message'&&Date.now()-new Date(e.created_at).getTime()<9000).slice(0,3):[];
  for(const e of recent){
    const from=graph.positions.get(e.payload.from_id),to=graph.positions.get(e.payload.to_id);
    if(!from||!to)continue;
    const fx=from.x+196,fy=from.y+65,tx=to.x+196,ty=to.y+65;
    const d='M '+fx+' '+fy+' C '+(fx+90)+' '+fy+', '+(tx+90)+' '+ty+', '+tx+' '+ty;
    paths+='<path class="message-route" d="'+d+'" marker-end="url(#messageArrow)"/><circle class="message-packet" r="4"><animateMotion dur="1.6s" repeatCount="indefinite" path="'+d+'"/></circle>';
  }
  svg.innerHTML=paths;
  let signal=document.getElementById('messageSignal');
  if(!signal){signal=document.createElement('div');signal.id='messageSignal';signal.className='message-signal';$('mapViewport').append(signal);}
  signal.hidden=!recent.length;
  if(recent.length){const p=recent[0].payload;signal.textContent=label(state.agents.get(p.from_id)?.role)+' → '+label(state.agents.get(p.to_id)?.role)+' · '+p.kind;}
  for(const [id,button] of elements)if(!state.agents.has(id)){button.remove();elements.delete(id);}
  for(const [index,a] of [...state.agents.values()].entries()){
    const pos=graph.positions.get(a.id);if(!pos)continue;
    let button=elements.get(a.id);
    const isNew=!button;
    if(isNew){
      button=document.createElement("button");button.type="button";button.dataset.id=a.id;
      button.addEventListener("click",()=>selectAgent(a.id));$("nodes").append(button);elements.set(a.id,button);
    }
    button.className="agent-node "+a.status+(selected===a.id?" selected":"")+(isNew&&!state.replay?" new":"")+(recent.some(e=>e.payload.from_id===a.id||e.payload.to_id===a.id)?" talking":"");
    button.style.left=pos.x+"px";button.style.top=pos.y+"px";button.style.setProperty("--agent-color",colorFor(a));
    button.setAttribute("aria-label",label(a.role)+", "+statusName(a.status)+". "+a.purpose);
    button.setAttribute("aria-pressed",String(selected===a.id));
    const task=[...state.tasks.values()].find(t=>t.agent_id===a.id&&t.status==="running");
    const html=(a.parent_id?"":'<span class="root-label">MISSION CONTROLLER</span>')+bot(colorFor(a))+
      '<span class="node-symbol" aria-hidden="true">'+symbol(a.status)+'</span><span class="node-name">'+esc(label(a.role))+
      '</span><span class="node-task">'+esc(task?.description||a.purpose)+'</span><span class="node-bottom"><span class="node-access">'+
      (a.capabilities?.length||0)+' capabilities</span><span class="node-state">'+esc(statusName(a.status))+'</span></span>';
    if(button.innerHTML!==html)button.innerHTML=html;
    if(isNew&&!state.replay)setTimeout(()=>button.classList.remove("new"),850);
  }
  if(!selected&&state.agents.size)selected=state.agents.keys().next().value;
  renderInspector();
  renderActivity();
  renderQuestion();
  renderReplayHud();
  $("resultPanel").hidden=!mission?.result||state.preview||!replayLive;
  if(mission?.result){
    $("resultTitle").textContent=status==="completed"?"Here’s what the crew delivered.":status==="blocked"?"The mission needs a missing capability.":status==="stopped"?"All execution stopped.":"The mission couldn’t finish.";
    $("resultText").textContent=mission.result.summary||mission.result.reason||mission.result.error||"";
    const meta=resultMetaText(mission);
    if($("resultMeta")){$("resultMeta").hidden=!meta;$("resultMeta").textContent=meta;}
  }
}
function selectAgent(id){
  selected=id;
  $("announcement").textContent=label(state.agents.get(id)?.role)+" selected";
  schedule();
}
function renderInspector(){
  const a=state.agents.get(selected);if(!a)return;
  const tasks=[...state.tasks.values()].filter(t=>t.agent_id===a.id),current=tasks.find(t=>t.status==="running")||tasks.at(-1);
  const parent=state.agents.get(a.parent_id),children=[...state.agents.values()].filter(c=>c.parent_id===a.id);
  const output=current?.output||a.output;
  const missionLive=replayLive&&!state.preview&&!terminal.has(state.mission?.status||"");
  const canKill=missionLive&&!terminal.has(a.status);
  const html='<div class="agent-detail"><div class="agent-detail-header">'+bot(colorFor(a))+'<div><h2>'+esc(label(a.role))+
    '</h2><span class="detail-status '+a.status+'">'+esc(statusName(a.status))+' · LEVEL '+a.depth+'</span></div></div>'+
    '<div class="detail-label">CURRENT OBJECTIVE</div><p class="detail-purpose">'+esc(current?.description||a.purpose)+'</p>'+
    '<div class="detail-label">CAPABILITIES</div><div class="access-list">'+(a.capabilities||[]).map(c=>'<span class="access-chip">'+esc(c)+'</span>').join("")+
    '</div><div class="relationships"><span>Reports to</span>'+(parent?'<button type="button" id="selectParent">'+esc(label(parent.role))+' ↗</button>':'<span>You</span>')+'</div>'+
    '<div class="relationships"><span>Direct reports</span><span>'+children.length+' agents</span></div>'+
    (output?'<div class="detail-label">RESULT</div><div class="detail-output">'+esc(output.finding||JSON.stringify(output))+'</div>':
    '<div class="detail-label">RIGHT NOW</div><p class="detail-purpose">'+esc(a.status==="running"?a.activity||"Considering the next step…":statusName(a.status))+'</p>')+
    (canKill?'<button type="button" class="kill-agent" id="killAgent">Kill this agent</button>':'')+
    '<div class="detail-label">COMMUNICATIONS</div>'+state.events.filter(e=>e.event_type==='agent.message'&&(e.payload.from_id===a.id||e.payload.to_id===a.id)).slice(0,3).map(e=>'<p class="detail-purpose message-detail">'+esc(label(state.agents.get(e.payload.from_id)?.role))+' → '+esc(label(state.agents.get(e.payload.to_id)?.role))+'<br><small>'+esc(e.payload.kind)+' · '+esc(e.payload.text.slice(0,160))+'</small></p>').join('')+
    '<div class="detail-usage">'+esc(a.model||health?.openai?.model||"")+(a.tokens?' · '+a.tokens.toLocaleString()+' tokens':'')+'</div></div>';
  const inspector=$("inspectorContent");
  if(inspector.innerHTML!==html){const scroll=inspector.querySelector(".detail-output")?.scrollTop||0;inspector.innerHTML=html;
    if(inspector.querySelector(".detail-output"))inspector.querySelector(".detail-output").scrollTop=scroll;
    if(parent)$("selectParent").onclick=()=>{selectAgent(parent.id);focusAgent(parent.id);};
    if($("killAgent"))$("killAgent").onclick=()=>{killSelectedAgent();};
  }
}
function describe(e){
  const p=e.payload||{},a=state.agents.get(e.actor_id),name=label(a?.role);
  switch(e.event_type){
    case "agent.message":return '<b>'+esc(label(state.agents.get(p.from_id)?.role))+'</b> → '+esc(label(state.agents.get(p.to_id)?.role))+' · '+esc(p.kind);
    case "agent.spawned":return "<b>"+esc(label(p.role))+"</b> joined the crew";
    case "agent.killed":return "<b>"+esc(label(p.role||a?.role))+"</b> was killed";
    case "controller.decision":return "<b>Controller</b> · "+esc(p.action==="spawn"?"delegated to "+label(p.role):p.action==="finish"?"assembled the final answer":p.action==="ask"?"asked the user a question":p.reason||p.action);
    case "mission.question":return "<b>Waiting for you</b> · "+esc(p.question||"A question is unanswered");
    case "user.answered":return "<b>Answer received</b> · "+esc(p.question||p.question_id||"question");
    case "llm.started":return "<b>"+esc(name)+"</b> is "+(p.kind==="decision"?"deciding the next move":p.kind==="verification"?"verifying the claimed result":"working");
    case "llm.completed":return "<b>"+esc(name)+"</b> · "+((p.input_tokens||0)+(p.output_tokens||0)+(p.reasoning_tokens||0)).toLocaleString()+" tokens";
    case "budget.updated":return p.known===true&&typeof p.token_spent==="number"
      ?"<b>Spend</b> · est. "+esc(formatUsd(p.token_spent)||String(p.token_spent))+(typeof p.token_budget==="number"?" / "+esc(formatUsd(p.token_budget)||String(p.token_budget)):"")
      :"<b>Spend</b> · estimate unavailable";
    case "budget.warning":return typeof p.token_spent==="number"&&typeof p.token_budget==="number"
      ?"<b>Budget warning</b> · est. "+esc(formatUsd(p.token_spent)||String(p.token_spent))+" / "+esc(formatUsd(p.token_budget)||String(p.token_budget))
      :"<b>Budget warning</b> · estimate unavailable";
    case "verification.started":return "<b>Verifier</b> is checking the claimed result";
    case "verification.passed":return "<b>Verifier</b> accepted the claimed result";
    case "verification.failed":return "<b>Verifier</b> rejected the claim"+(p.failure_class?" · "+esc(p.failure_class):"")+(p.rationale?" · "+esc(p.rationale):"");
    case "task.completed":return "<b>"+esc(name)+"</b> delivered a result";
    case "task.blocked":return "<b>"+esc(name)+"</b> needs a missing capability";
    case "mission.started":return "The mission is underway";
    case "mission.completed":return "<b>Mission complete.</b> Result ready below";
    case "mission.stopped":return "<b>Execution stopped</b>";
    case "mission.failed":return "<b>Mission failed</b>"+(p.failure_class?" · "+esc(p.failure_class):"")+(p.error?" · "+esc(p.error):"");
    case "mission.blocked":return "<b>Mission blocked</b> · "+esc(p.reason||"");
    default:return "";
  }
}
function renderActivity(){
  const html=state.events.filter(e=>describe(e)).slice(0,30).map(e=>'<li>'+describe(e)+'<time>'+
    new Date(e.created_at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"})+'</time></li>').join("");
  $("activity").innerHTML=html||'<li class="empty-activity">The mission’s story will appear here.</li>';
}
function pendingQuestion(){
  if(state.preview||!replayLive)return null;
  const open=state.mission?.pending_question;
  return open&&open.question_id?open:null;
}
function applyQuestionEvent(e){
  if(!state.mission||state.preview)return;
  const p=e.payload||{};
  if(e.event_type==="mission.question"){
    state.mission.pending_question=p;
    state.mission.status="waiting";
  }
  if(e.event_type==="mission.waiting"&&(p.question_id||p.question||state.mission.pending_question)){
    state.mission.status="waiting";
    if(p.question_id&&p.question)state.mission.pending_question={...state.mission.pending_question,...p};
  }
  if(e.event_type==="user.answered"){
    const open=state.mission.pending_question;
    if(!open||!p.question_id||open.question_id===p.question_id)state.mission.pending_question=null;
  }
  if(e.event_type==="mission.running")state.mission.status="running";
  if(e.event_type.startsWith("mission.")&&terminal.has(e.event_type.split(".")[1]))state.mission.pending_question=null;
}
function renderQuestion(){
  const panel=$("questionPanel");
  if(!panel)return;
  const open=pendingQuestion();
  const live=!!open&&!terminal.has(state.mission?.status||"");
  panel.hidden=!live;
  if($("questionText"))$("questionText").textContent=open?.question||"";
  if($("answerSend"))$("answerSend").disabled=!live;
}
async function request(path,options){
  const r=await fetch(path,options);let data;
  try{data=await r.json();}catch{throw Error("The server returned an unreadable response");}
  if(!r.ok)throw Error(typeof data.detail==="string"?data.detail:"Request failed ("+r.status+")");
  return data;
}
function disconnect(){
  generation++;clearTimeout(retry);clearTimeout(previewTimer);stopReplayPlay();if(ws){ws.onclose=null;ws.close();ws=null;}
}
function reset(mission){
  stopReplayPlay();
  eventLog=[];replayCursor=-1;replayLive=true;sourceMission=mission||null;
  state=newState(mission);selected=null;elements.clear();$("nodes").replaceChildren();$("activity").replaceChildren();
  $("resultPanel").hidden=true;if($("resultMeta")){$("resultMeta").hidden=true;$("resultMeta").textContent="";}
  if($("questionPanel"))$("questionPanel").hidden=!mission?.pending_question;
  if($("answerText"))$("answerText").value="";
  showNotice("");setCommandStatus("");zoom=1;$("zoomValue").textContent="100%";clearAlerts();
  if(hudTick){clearInterval(hudTick);hudTick=null;}
}
function stopReplayPlay(){
  if(replayTimer){clearInterval(replayTimer);replayTimer=null;}
}
function ingestRecorded(e){
  if(!recordEvent(eventLog,e))return false;
  if(replayLive){
    replayCursor=eventLog.length-1;
    applyEvent(state,e);
    applyQuestionEvent(e);
  }
  return true;
}
function showReplayAt(index,playing=false){
  if(state.preview)return;
  stopReplayPlay();
  const cursor=clampReplayIndex(index,eventLog.length);
  replayCursor=cursor;
  replayLive=isReplayLive(cursor,eventLog.length);
  const projected=projectEvents(sourceMission,eventLog,cursor);
  projected.preview=false;
  projected.replay=!replayLive;
  state=projected;
  if(selected&&!state.agents.has(selected))selected=null;
  elements.clear();
  if($("nodes"))$("nodes").replaceChildren();
  if(playing&&!replayLive){
    replayTimer=setInterval(()=>{
      const next=stepReplay(replayCursor,eventLog.length,1);
      const live=isReplayLive(next,eventLog.length);
      replayCursor=next;
      replayLive=live;
      const step=projectEvents(sourceMission,eventLog,next);
      step.preview=false;
      step.replay=!live;
      state=step;
      if(selected&&!state.agents.has(selected))selected=null;
      elements.clear();
      if($("nodes"))$("nodes").replaceChildren();
      schedule();
      if(live)stopReplayPlay();
    },400);
  }
  schedule();
}
function renderReplayHud(){
  const hud=$("replayHud");
  if(!hud)return;
  const playing=!!replayTimer;
  const view=replayView(eventLog,replayCursor,{preview:state.preview,playing,mission:sourceMission||state.mission});
  hud.hidden=!state.mission||state.preview;
  hud.dataset.live=view.live?"true":"false";
  if($("replayMode")){
    $("replayMode").textContent=view.label;
    $("replayMode").className="hud-chip mode "+(view.preview?"preview":view.live?"replay-live":"replay");
  }
  if($("replayCaption"))$("replayCaption").textContent=view.caption;
  if($("replayPosition"))$("replayPosition").textContent=view.positionLabel;
  if($("replayEvent"))$("replayEvent").textContent=view.eventType||"—";
  const scrub=$("replayScrub");
  if(scrub){
    const max=Math.max(0,view.total-1);
    scrub.max=String(max);
    scrub.value=String(Math.max(0,view.cursor));
    scrub.disabled=view.disabled;
  }
  const disable=view.disabled;
  if($("replayPrev"))$("replayPrev").disabled=disable||view.cursor<=0;
  if($("replayNext"))$("replayNext").disabled=disable||view.live;
  if($("replayLiveBtn"))$("replayLiveBtn").disabled=disable||view.live;
  if($("replayPlay")){
    $("replayPlay").disabled=disable||view.total<2||view.live;
    $("replayPlay").textContent=playing?"Pause":"Play";
  }
}
function connect(id,gen){
  if(gen!==generation)return;
  const liveFrom=Date.now();
  ws=new WebSocket((location.protocol==="https:"?"wss:":"ws:")+"//"+location.host+"/api/missions/"+id+"/stream");
  ws.onopen=()=>{if(gen===generation&&!terminal.has(state.mission?.status||""))connection("Live connection","live");};
  ws.onmessage=message=>{
    if(gen!==generation)return;
    try{
      const e=JSON.parse(message.data);
      if(ingestRecorded(e)){
        schedule();
        if(replayLive){
          considerAlert(e,liveFrom);
          if(e.event_type==="mission.question"){
            const created=e.created_at?new Date(e.created_at).getTime():NaN;
            if(!(Number.isFinite(created)&&created<liveFrom-2000)){
              pushAlert({level:"warning",title:"Human answer required",detail:(e.payload&&e.payload.question)||"A question is unanswered",event_type:"mission.question"});
            }
          }
          if(e.event_type==='agent.message')setTimeout(schedule,9100);
        }
        if(e.event_type.startsWith("mission.")&&terminal.has(e.event_type.split(".")[1]))refreshHistory();
      }
    }catch{showNotice("An event could not be read. Reconnect to restore the mission.");}
  };
  ws.onerror=()=>connection("Connection interrupted","disconnected");
  ws.onclose=()=>{
    if(gen!==generation)return;
    const status=state.mission?.status||"";
    if(terminal.has(status)){connection("Mission "+status,status==="completed"?"live":"disconnected");return;}
    connection("Reconnecting…","disconnected");
    retry=setTimeout(()=>connect(id,gen),2000);
  };
}
async function loadMission(id){
  disconnect();const gen=generation;
  try{
    const m=await request("/api/missions/"+id);if(gen!==generation)return;
    reset(m);localStorage.setItem("swarm.mission",id);$("goal").value=m.goal;
    try{
      const events=await request("/api/missions/"+id+"/events");
      if(gen!==generation)return;
      for(const e of events)ingestRecorded(e);
    }catch{}
    connect(id,gen);schedule();
  }catch(error){showNotice(error.message);}
}
async function refreshHistory(){
  try{
    const missions=await request("/api/missions");
    $("history").replaceChildren(new Option("Mission history",""));
    for(const m of missions)$("history").add(new Option(m.goal.slice(0,60)+" · "+m.status,m.id));
    if(state.mission&&!state.preview)$("history").value=state.mission.id;
    return missions;
  }catch{return [];}
}
$("missionForm").addEventListener("submit",async e=>{
  e.preventDefault();if($("launch").disabled)return;
  showNotice("");$("launch").disabled=true;armNotifications();
  try{
    const m=await request("/api/missions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({goal:$("goal").value})});
    disconnect();reset(m);localStorage.setItem("swarm.mission",m.id);connect(m.id,generation);
    schedule();refreshHistory();
  }catch(error){showNotice(error.message);$("launch").disabled=false;}
});
$("stopAll").addEventListener("click",async()=>{
  $("stopAll").disabled=true;$("stopAll").innerHTML="<span>■</span> STOPPING…";
  try{
    haltPreviewLocally();
    const result=await request("/api/stop-all",{method:"POST"});
    $("announcement").textContent="All mission execution stopped";
    connection("All execution stopped");
    if(state.mission&&!state.preview){
      const mode=state.mission.mode;
      const m=await request("/api/missions/"+state.mission.id);
      state.mission=m;if(mode)state.mission.mode=mode;schedule();
    }
    if(result.active_missions)showNotice("Some executions are still shutting down.");
  }catch(error){showNotice("Shutdown could not be confirmed: "+error.message);}
  finally{$("stopAll").disabled=false;$("stopAll").innerHTML="<span>■</span> STOP ALL";refreshHistory();}
});
async function killSelectedAgent(){
  const a=state.agents.get(selected);if(!a)return;
  const btn=$("killAgent");if(btn)btn.disabled=true;
  try{
    if(state.preview){
      a.status="stopped";
      for(const t of state.tasks.values()){
        if(t.agent_id===a.id&&(t.status==="pending"||t.status==="running"))t.status="stopped";
      }
      $("announcement").textContent=label(a.role)+" stopped";
      schedule();
      return;
    }
    if(!state.mission?.id||terminal.has(state.mission.status||""))return;
    await request("/api/missions/"+state.mission.id+"/agents/"+a.id+"/kill",{method:"POST"});
    $("announcement").textContent=label(a.role)+" stopped";
  }catch(error){showNotice("Could not kill that agent: "+error.message);}
  finally{schedule();}
}
function commandContext(){
  return {
    missionId:state.preview?null:state.mission?.id||null,
    preview:!!state.preview,
    pendingQuestionId:pendingQuestion()?.question_id||null,
    selectedAgentId:selected||null,
    killAvailable,
  };
}
function commandSuccessMessage(resolved,result){
  if(resolved.action==="stop"){
    if(!result||typeof result.status!=="string")return null;
    return "Mission "+result.status;
  }
  if(resolved.action==="stop-all"){
    if(!result||result.status!=="stopped"||!Array.isArray(result.mission_ids))return null;
    let message="Stopped "+result.mission_ids.length+" mission(s)";
    if(result.active_missions)message+=" · some executions are still shutting down";
    return message;
  }
  if(resolved.action==="answer"){
    if(!result||result.accepted!==true)return null;
    return "Answer accepted";
  }
  if(resolved.action==="kill"){
    if(!result||typeof result.status!=="string"||!result.agent_id)return null;
    return "Agent "+result.status;
  }
  return null;
}
async function runCommand(raw){
  const parsed=parseCommand(raw);
  if(!parsed.ok){setCommandStatus(parsed.error,"error");return;}
  const resolved=resolveCommand(parsed,commandContext());
  if(!resolved.ok){setCommandStatus(resolved.error,"error");return;}
  const btn=$("commandSend");
  if(btn)btn.disabled=true;
  try{
    if(resolved.action==="stop-all")haltPreviewLocally();
    const options={method:resolved.method||"POST"};
    if(resolved.body){
      options.headers={"Content-Type":"application/json"};
      options.body=JSON.stringify(resolved.body);
    }
    const result=await request(resolved.path,options);
    const message=commandSuccessMessage(resolved,result);
    if(!message){setCommandStatus("Command did not confirm success","error");return;}
    if(resolved.action==="stop"||resolved.action==="stop-all"){
      $("announcement").textContent=message;
      if(state.mission&&!state.preview){
        const mode=state.mission.mode;
        const m=await request("/api/missions/"+state.mission.id);
        state.mission=m;if(mode)state.mission.mode=mode;
      }
      if(resolved.action==="stop-all")connection("All execution stopped");
    }
    if(resolved.action==="answer"){
      if($("answerText"))$("answerText").value="";
      renderQuestion();
    }
    setCommandStatus(message,"ok");
    if($("commandInput"))$("commandInput").value="";
    refreshHistory();
    schedule();
  }catch(error){setCommandStatus(error.message,"error");}
  finally{if(btn)btn.disabled=false;}
}
if($("commandForm"))$("commandForm").addEventListener("submit",e=>{
  e.preventDefault();
  runCommand($("commandInput")?$("commandInput").value:"");
});
$("history").addEventListener("change",()=>{if($("history").value)loadMission($("history").value);});
$("answerForm").addEventListener("submit",async e=>{
  e.preventDefault();
  const open=pendingQuestion(),id=state.mission?.id;
  if(!open||!id||state.preview)return;
  const text=($("answerText").value||"").trim();
  if(!text){showNotice("Answer must not be empty");return;}
  $("answerSend").disabled=true;
  try{
    await request("/api/missions/"+id+"/answers/"+encodeURIComponent(open.question_id),{
      method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({answer:text})
    });
    $("answerText").value="";
    showNotice("");
  }catch(error){showNotice(error.message);}
  finally{$("answerSend").disabled=false;renderQuestion();}
});
$("copyResult").addEventListener("click",async()=>{
  try{await navigator.clipboard.writeText($("resultText").textContent);$("copyResult").textContent="Copied";setTimeout(()=>$("copyResult").textContent="Copy result",1500);}
  catch{showNotice("Copy unavailable. Select the result text to copy it.");}
});
function focusAgent(id){const pos=graph?.positions.get(id);if(!pos)return;$("mapViewport").scrollTo({left:(pos.x+105)*zoom-$("mapViewport").clientWidth/2,top:Math.max(0,pos.y*zoom-120),behavior:"smooth"});}
function setZoom(value){
  const viewport=$("mapViewport"),old=zoom;zoom=Math.max(.45,Math.min(1.4,value));
  const cx=(viewport.scrollLeft+viewport.clientWidth/2)/old,cy=(viewport.scrollTop+viewport.clientHeight/2)/old;
  $("zoomValue").textContent=Math.round(zoom*100)+"%";render();
  viewport.scrollLeft=cx*zoom-viewport.clientWidth/2;viewport.scrollTop=cy*zoom-viewport.clientHeight/2;
}
$("zoomIn").onclick=()=>setZoom(zoom+.1);$("zoomOut").onclick=()=>setZoom(zoom-.1);
$("fit").onclick=()=>{if(graph){setZoom(Math.min(1,($("mapViewport").clientWidth-30)/graph.width));$("mapViewport").scrollTop=0;}};
let drag=null;
$("mapViewport").addEventListener("pointerdown",e=>{
  if(e.pointerType!=="mouse"||e.button!==0||e.target.closest("button"))return;
  drag={x:e.clientX,y:e.clientY,left:$("mapViewport").scrollLeft,top:$("mapViewport").scrollTop};
  $("mapViewport").setPointerCapture(e.pointerId);$("mapViewport").classList.add("panning");
});
$("mapViewport").addEventListener("pointermove",e=>{if(drag){$("mapViewport").scrollLeft=drag.left+drag.x-e.clientX;$("mapViewport").scrollTop=drag.top+drag.y-e.clientY;}});
for(const type of ["pointerup","pointercancel"])$("mapViewport").addEventListener(type,()=>{drag=null;$("mapViewport").classList.remove("panning");});
new ResizeObserver(()=>schedule()).observe($("mapViewport"));
function preview(){
  disconnect();reset({id:"preview",goal:"Design a launch plan for a small business",status:"running",created_at:new Date().toISOString()});state.preview=true;
  const specs=[
    ["root",null,"mission_controller","Turn the goal into useful work",["spawn","coordinate","reason"],"running"],
    ["strategy","root","strategist","Define the audience and launch priorities",["reason","write"],"completed"],
    ["research","root","researcher","Identify the assumptions worth testing",["reason"],"running"],
    ["builder","strategy","copywriter","Draft the first landing page message",["write"],"running"],
    ["reviewer","strategy","reviewer","Check the plan against the original goal",["review"],"created"],
    ["access","research","market_analyst","Needs a web connection for current data",["reason"],"blocked"],
  ];
  let i=0;
  function next(){
    if(i>=specs.length){
      for(const [j,from,to,kind,text] of [[0,'research','strategy','question','Which customer group should we investigate first?'],[1,'strategy','builder','idea','Focus the first headline on getting paid on time.'],[2,'builder','root','result','The first draft is ready for review.']])setTimeout(()=>{if(!state.preview)return;applyEvent(state,{id:'message-'+j,event_type:'agent.message',actor_id:from,payload:{from_id:from,to_id:to,kind,text},created_at:new Date().toISOString()});schedule();setTimeout(schedule,9200);},j*2400);
      return;
    }
    const [id,parent_id,role,purpose,capabilities,status]=specs[i],a={id,parent_id,role,purpose,capabilities,status,depth:parent_id?(state.agents.get(parent_id)?.depth||0)+1:0};
    applyEvent(state,{id:"preview-"+i,event_type:"agent.spawned",actor_id:id,payload:a,created_at:new Date().toISOString()});
    if(id==="strategy")a.output={finding:"Start with one audience, one clear offer and one measurable launch goal."};
    schedule();i++;previewTimer=setTimeout(next,420);
  }
  next();
}
$("preview").onclick=preview;$("emptyPreview").onclick=preview;
if($("replayPrev"))$("replayPrev").onclick=()=>{if(state.preview)return;showReplayAt(stepReplay(replayCursor,eventLog.length,-1));};
if($("replayNext"))$("replayNext").onclick=()=>{if(state.preview)return;showReplayAt(stepReplay(replayCursor,eventLog.length,1));};
if($("replayLiveBtn"))$("replayLiveBtn").onclick=()=>{if(state.preview)return;showReplayAt(eventLog.length-1);};
if($("replayPlay"))$("replayPlay").onclick=()=>{
  if(state.preview)return;
  if(replayTimer){stopReplayPlay();schedule();return;}
  showReplayAt(replayCursor,true);
};
if($("replayScrub"))$("replayScrub").addEventListener("input",()=>{
  if(state.preview||$("replayScrub").disabled)return;
  showReplayAt(Number($("replayScrub").value));
});
async function initialize(){
  try{
    const spec=await request("/openapi.json");
    killAvailable=killRoutePresent(spec);
  }catch{killAvailable=false;}
  try{health=await request("/api/health");const o=health.openai;
    $("brain").innerHTML='<span class="brain-dot"></span><div><strong>'+esc(o.model)+'</strong><small>'+esc(o.reasoning_effort)+' reasoning · '+(o.configured?'connected':'key needed')+'</small></div>';
    connection(o.configured?"Ready to think":"API key needed",o.configured?"live":"disconnected");
    if(!o.configured)showNotice("OpenAI is not configured on the server yet.");
  }catch{connection("Server unavailable","disconnected");showNotice("Cannot reach the local server.");}
  const missions=await refreshHistory(),urlId=new URL(location.href).searchParams.get("mission"),saved=urlId||localStorage.getItem("swarm.mission");
  if(saved&&missions.some(m=>m.id===saved))await loadMission(saved);else schedule();
}
initialize();
