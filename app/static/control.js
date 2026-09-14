import {newState,applyEvent,layoutTree,terminal,alertFromEvent,resultMetaText,missionMode} from "./state.mjs";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g,c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const label = role => String(role||"Agent").replaceAll("_"," ");
const statusName = status => ({created:"Ready",running:"Thinking",completed:"Done",blocked:"Blocked",failed:"Failed",stopped:"Stopped",pending:"Queued"}[status] || status);
const symbol = status => ({created:"·",running:"",completed:"✓",blocked:"?",failed:"!",stopped:"■"}[status] || "·");
const colors = ["#c6b4ef","#edbd9e","#aed8cf","#e6cd90","#b5cbe3","#dfb9ca"];
let state=newState(), selected=null, ws=null, generation=0, retry=null, zoom=1, graph=null, frame=0, previewTimer=null, health=null, hudTick=null, notifyArmed=false;
const elements=new Map();
const bot = color => '<span class="bot" style="--agent-color:'+color+'" aria-hidden="true"><span class="ear ear-left"></span><span class="ear ear-right"></span><span class="visor"><i></i><i></i><b class="mouth"></b></span></span>';
function colorFor(a) {if(!a.parent_id)return colors[0];let n=0;for(const c of a.role)n=(n*31+c.charCodeAt(0))>>>0;return colors[1+n%(colors.length-1)];}
function showNotice(message) {$("notice").textContent=message;$("notice").hidden=!message;}
function connection(text,cls="") {$("connection").className="connection "+cls;$("connection").innerHTML="<i></i>"+esc(text);}
function formatUsd(value){
  if(!Number.isFinite(value))return "—";
  if(value===0)return "$0";
  if(value<0.01)return "$"+value.toFixed(4);
  return "$"+value.toFixed(2);
}
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
  if($("hudTokens"))$("hudTokens").textContent=(state.usage.input+state.usage.output).toLocaleString();
  if($("hudSpend")){
    $("hudSpend").textContent=state.usage.known?formatUsd(state.usage.cost):"—";
  }
  if($("hudElapsed")){
    const start=mission?.created_at?new Date(mission.created_at).getTime():NaN;
    $("hudElapsed").textContent=Number.isFinite(start)?formatElapsed(Date.now()-start):"—";
  }
  const running=!!mission&&!terminal.has(status);
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
  item.innerHTML="<header><strong>"+esc(alert.title)+"</strong>"+klass+'<button type="button" class="alert-dismiss" aria-label="Dismiss">×</button></header>'+(alert.detail?"<p>"+esc(alert.detail)+"</p>":"");
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
  $("modeLabel").textContent=state.preview?"PREVIEW":status.toUpperCase();
  $("modeLabel").className="mode-tag "+status;
  $("agentCount").textContent=state.agents.size;
  $("taskCount").textContent=[...state.tasks.values()].filter(t=>t.status==="completed").length;
  $("tokenCount").textContent=(state.usage.input+state.usage.output).toLocaleString();
  $("eventCount").textContent=state.seen.size+" events";
  $("emptyMap").hidden=state.agents.size>0;
  $("launch").disabled=!!mission&&!terminal.has(status)&&!state.preview;
  $("launch").innerHTML=$("launch").disabled?'Mission running <span>⌁</span>':'Launch mission <span>↗</span>';
  $("missionCaption").textContent=state.preview?"Interactive preview · no models or tools are running":mission?.goal||"One mission. As many minds as it needs.";
  if(state.preview)connection("Preview");
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
  const recent=state.events.filter(e=>e.event_type==='agent.message'&&Date.now()-new Date(e.created_at).getTime()<9000).slice(0,3);
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
    button.className="agent-node "+a.status+(selected===a.id?" selected":"")+(isNew?" new":"")+(recent.some(e=>e.payload.from_id===a.id||e.payload.to_id===a.id)?" talking":"");
    button.style.left=pos.x+"px";button.style.top=pos.y+"px";button.style.setProperty("--agent-color",colorFor(a));
    button.setAttribute("aria-label",label(a.role)+", "+statusName(a.status)+". "+a.purpose);
    button.setAttribute("aria-pressed",String(selected===a.id));
    const task=[...state.tasks.values()].find(t=>t.agent_id===a.id&&t.status==="running");
    const html=(a.parent_id?"":'<span class="root-label">MISSION CONTROLLER</span>')+bot(colorFor(a))+
      '<span class="node-symbol" aria-hidden="true">'+symbol(a.status)+'</span><span class="node-name">'+esc(label(a.role))+
      '</span><span class="node-task">'+esc(task?.description||a.purpose)+'</span><span class="node-bottom"><span class="node-access">'+
      (a.capabilities?.length||0)+' capabilities</span><span class="node-state">'+esc(statusName(a.status))+'</span></span>';
    if(button.innerHTML!==html)button.innerHTML=html;
    if(isNew)setTimeout(()=>button.classList.remove("new"),850);
  }
  if(!selected&&state.agents.size)selected=state.agents.keys().next().value;
  renderInspector();
  renderActivity();
  renderQuestion();
  $("resultPanel").hidden=!mission?.result||state.preview;
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
  const html='<div class="agent-detail"><div class="agent-detail-header">'+bot(colorFor(a))+'<div><h2>'+esc(label(a.role))+
    '</h2><span class="detail-status '+a.status+'">'+esc(statusName(a.status))+' · LEVEL '+a.depth+'</span></div></div>'+
    '<div class="detail-label">CURRENT OBJECTIVE</div><p class="detail-purpose">'+esc(current?.description||a.purpose)+'</p>'+
    '<div class="detail-label">CAPABILITIES</div><div class="access-list">'+(a.capabilities||[]).map(c=>'<span class="access-chip">'+esc(c)+'</span>').join("")+
    '</div><div class="relationships"><span>Reports to</span>'+(parent?'<button type="button" id="selectParent">'+esc(label(parent.role))+' ↗</button>':'<span>You</span>')+'</div>'+
    '<div class="relationships"><span>Direct reports</span><span>'+children.length+' agents</span></div>'+
    (output?'<div class="detail-label">RESULT</div><div class="detail-output">'+esc(output.finding||JSON.stringify(output))+'</div>':
    '<div class="detail-label">RIGHT NOW</div><p class="detail-purpose">'+esc(a.status==="running"?a.activity||"Considering the next step…":statusName(a.status))+'</p>')+
    '<div class="detail-label">COMMUNICATIONS</div>'+state.events.filter(e=>e.event_type==='agent.message'&&(e.payload.from_id===a.id||e.payload.to_id===a.id)).slice(0,3).map(e=>'<p class="detail-purpose message-detail">'+esc(label(state.agents.get(e.payload.from_id)?.role))+' → '+esc(label(state.agents.get(e.payload.to_id)?.role))+'<br><small>'+esc(e.payload.kind)+' · '+esc(e.payload.text.slice(0,160))+'</small></p>').join('')+
    '<div class="detail-usage">'+esc(a.model||health?.openai?.model||"")+(a.tokens?' · '+a.tokens.toLocaleString()+' tokens':'')+'</div></div>';
  const inspector=$("inspectorContent");
  if(inspector.innerHTML!==html){const scroll=inspector.querySelector(".detail-output")?.scrollTop||0;inspector.innerHTML=html;
    if(inspector.querySelector(".detail-output"))inspector.querySelector(".detail-output").scrollTop=scroll;
    if(parent)$("selectParent").onclick=()=>{selectAgent(parent.id);focusAgent(parent.id);};
  }
}
function describe(e){
  const p=e.payload||{},a=state.agents.get(e.actor_id),name=label(a?.role);
  switch(e.event_type){
    case "agent.message":return '<b>'+esc(label(state.agents.get(p.from_id)?.role))+'</b> → '+esc(label(state.agents.get(p.to_id)?.role))+' · '+esc(p.kind);
    case "agent.spawned":return "<b>"+esc(label(p.role))+"</b> joined the crew";
    case "controller.decision":return "<b>Controller</b> · "+esc(p.action==="spawn"?"delegated to "+label(p.role):p.action==="finish"?"assembled the final answer":p.action==="ask"?"asked the user a question":p.reason||p.action);
    case "mission.question":return "<b>Waiting for you</b> · "+esc(p.question||"A question is unanswered");
    case "user.answered":return "<b>Answer received</b> · "+esc(p.question||p.question_id||"question");
    case "llm.started":return "<b>"+esc(name)+"</b> is "+(p.kind==="decision"?"deciding the next move":p.kind==="verification"?"verifying the claimed result":"working");
    case "llm.completed":return "<b>"+esc(name)+"</b> · "+((p.input_tokens||0)+(p.output_tokens||0)).toLocaleString()+" tokens";
    case "budget.updated":return p.known?"<b>Spend</b> · est. "+esc(String(p.token_spent))+" / "+esc(String(p.token_budget))+" USD":"<b>Spend</b> · estimate unavailable";
    case "budget.warning":return "<b>Budget warning</b> · est. "+esc(String(p.token_spent))+" / "+esc(String(p.token_budget))+" USD";
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
  if(state.preview)return null;
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
  generation++;clearTimeout(retry);clearTimeout(previewTimer);if(ws){ws.onclose=null;ws.close();ws=null;}
}
function reset(mission){
  state=newState(mission);selected=null;elements.clear();$("nodes").replaceChildren();$("activity").replaceChildren();
  $("resultPanel").hidden=true;if($("resultMeta")){$("resultMeta").hidden=true;$("resultMeta").textContent="";}
  if($("questionPanel"))$("questionPanel").hidden=!mission?.pending_question;
  if($("answerText"))$("answerText").value="";
  showNotice("");zoom=1;$("zoomValue").textContent="100%";clearAlerts();
  if(hudTick){clearInterval(hudTick);hudTick=null;}
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
      if(applyEvent(state,e)){
        applyQuestionEvent(e);
        schedule();
        considerAlert(e,liveFrom);
        if(e.event_type==="mission.question"){
          const created=e.created_at?new Date(e.created_at).getTime():NaN;
          if(!(Number.isFinite(created)&&created<liveFrom-2000)){
            pushAlert({level:"warning",title:"Human answer required",detail:(e.payload&&e.payload.question)||"A question is unanswered",event_type:"mission.question"});
          }
        }
        if(e.event_type==='agent.message')setTimeout(schedule,9100);
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
      for(const e of events){applyEvent(state,e);applyQuestionEvent(e);}
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
    if(state.preview){
      clearTimeout(previewTimer);for(const a of state.agents.values())a.status="stopped";state.mission.status="stopped";
      state.mission.result={reason:"Preview halted"};
      pushAlert({level:"warning",title:"Execution stopped",detail:"Preview halted",event_type:"mission.stopped"});
      schedule();
    }
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
async function initialize(){
  try{health=await request("/api/health");const o=health.openai;
    $("brain").innerHTML='<span class="brain-dot"></span><div><strong>'+esc(o.model)+'</strong><small>'+esc(o.reasoning_effort)+' reasoning · '+(o.configured?'connected':'key needed')+'</small></div>';
    connection(o.configured?"Ready to think":"API key needed",o.configured?"live":"disconnected");
    if(!o.configured)showNotice("OpenAI is not configured on the server yet.");
  }catch{connection("Server unavailable","disconnected");showNotice("Cannot reach the local server.");}
  const missions=await refreshHistory(),urlId=new URL(location.href).searchParams.get("mission"),saved=urlId||localStorage.getItem("swarm.mission");
  if(saved&&missions.some(m=>m.id===saved))await loadMission(saved);else schedule();
}
initialize();
