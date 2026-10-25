import { computed, onUnmounted, reactive, ref, watch } from 'vue';

// Retain semantic unsaved drafts across a login redirect, in this app session only.
// Weak ownership prevents another account or a different app session from seeing them.
const sessionDrafts=new WeakMap();
const copy=value=>JSON.parse(JSON.stringify(value));
export const candidateKey=entry=>`${entry.duration_minutes}|${entry.start_time}|${entry.court_preference}|${entry.scope_label||''}`;
export const queueEntries=queue=>(queue?.candidates||[]).map(intent=>{
 const start=intent.preferred_start_times[0],end=Number(start.slice(0,2))*60+Number(start.slice(3))+intent.duration_minutes;
 const legacyScope=intent.venue_preference==='羽毛球（场馆未绑定）'?'羽毛球':'';
 return {court_preference:intent.court_preferences[0],start_time:start,end_time:`${String(Math.floor(end/60)).padStart(2,'0')}:${String(end%60).padStart(2,'0')}`,duration_minutes:intent.duration_minutes,scope_label:intent.query_scope_label||legacyScope};
});
export const orderQueueEntries=entries=>[...entries.filter(e=>e.duration_minutes===120),...entries.filter(e=>e.duration_minutes===60)];
export const queueEntriesFingerprint=entries=>JSON.stringify(orderQueueEntries(entries).map(e=>[e.duration_minutes,e.scope_label||'',e.court_preference,e.start_time,e.end_time]));
const ordered=orderQueueEntries;
const fingerprint=queueEntriesFingerprint;

export function useManualQueue(api,session,targetDate,targetCredentialId=()=>null,isActive=()=>true){
 const entries=ref([]),queues=ref([]),version=ref(0),status=ref('idle'),error=ref(''),blocked=ref(false),dirty=ref(false),latest=ref(undefined),history=ref(null),historyError=ref('');
 const historyCursor=ref(null),historyLoading=ref(false);
 let historySelection=null;
 let alive=true,generation=0,timer=null,inflight=false,owner='',lastSaved='[]',drafts=new Map(),listSequence=0,loadSequence=0,historySequence=0;
 let inflightCompletion=Promise.resolve();
 const authenticated=()=>session?.status==='authenticated'&&Boolean(session.user?.user_id);
 const valid=epoch=>alive&&epoch===generation&&authenticated();
 const rememberedByUser=sessionDrafts.get(session)||new Map();sessionDrafts.set(session,rememberedByUser);
 const date=computed(targetDate);
 const credentialId=computed(()=>typeof targetCredentialId==='function'?targetCredentialId():targetCredentialId?.value||targetCredentialId||null);
 const locked=computed(()=>status.value==='loading'||blocked.value||!authenticated()||!credentialId.value);
 const dateLocked=computed(()=>dirty.value||inflight||status.value==='saving'||blocked.value||status.value==='loading');
 const statusText=computed(()=>!credentialId.value?'先选择预约凭据':({idle:'',loading:'读取中…',saving:'保存中…',ready:version.value?`已自动保存 · v${version.value}`:'选格后自动保存',pending:'等待自动保存…',error:'未保存',conflict:'版本冲突',suspended:'登录失效 · 内容已保留'})[status.value]||'');
 let activeCredentialId=credentialId.value;
 const draftKey=(scope=activeCredentialId)=>`${scope||'unbound'}\0${date.value||''}`;
 function remember(scope=activeCredentialId){if(owner&&date.value)drafts.set(draftKey(scope),{entries:copy(entries.value),dirty:dirty.value,version:version.value,lastSaved});}
 async function refreshList(){if(!authenticated()||!credentialId.value||!api.queues){queues.value=[];return;}const epoch=generation,seq=++listSequence,selectedCredential=credentialId.value;try{const result=await api.queues(selectedCredential);if(valid(epoch)&&seq===listSequence&&selectedCredential===credentialId.value)queues.value=result.queues;}catch{/* Editor errors are surfaced separately. */}}
 async function load(){
  if(!isActive())return;
  clearTimeout(timer);const epoch=generation,seq=++loadSequence,selectedDate=date.value;
  if(!authenticated()||!selectedDate||!api.queue)return;
  if(!credentialId.value){entries.value=[];version.value=0;dirty.value=false;blocked.value=false;error.value='';latest.value=undefined;status.value='idle';return;}
  latest.value=undefined;closeHistory();error.value='';blocked.value=false;status.value='loading';
  const selectedCredential=credentialId.value,draft=drafts.get(draftKey());entries.value=copy(draft?.entries||[]);dirty.value=Boolean(draft?.dirty);version.value=draft?.version||0;lastSaved=draft?.lastSaved||'[]';
  try{
   const result=await api.queue(selectedDate,selectedCredential);if(!valid(epoch)||seq!==loadSequence||selectedDate!==date.value||selectedCredential!==credentialId.value)return;
   const remote=queueEntries(result.queue);
   if(draft?.dirty&&fingerprint(remote)!==fingerprint(draft.entries)){
    latest.value=result.queue;blocked.value=true;status.value='conflict';error.value='本地队列已保留，请比较最新版本后决定。';
   }else{entries.value=remote;version.value=result.queue?.version||0;lastSaved=fingerprint(remote);dirty.value=false;status.value='ready';remember();}
  }catch{if(valid(epoch)&&seq===loadSequence&&selectedCredential===credentialId.value){blocked.value=true;status.value='error';error.value='读取失败，当前队列已保留。';}}
 }
 function schedule(){clearTimeout(timer);if(!blocked.value&&dirty.value&&authenticated()){status.value=inflight?'saving':'pending';timer=setTimeout(flush,450);}}
 function change(next){if(locked.value)return;entries.value=ordered(copy(next));dirty.value=fingerprint(entries.value)!==lastSaved;error.value='';remember();if(dirty.value)schedule();else status.value=inflight?'saving':'ready';}
 async function flush(){
  clearTimeout(timer);
  if(inflight){const waitingGeneration=generation;await inflightCompletion;if(valid(waitingGeneration))return flush();return;}
  if(blocked.value||!dirty.value||!authenticated()||!api.saveQueue)return;
  const epoch=generation,selectedDate=date.value,selectedCredential=credentialId.value,sent=copy(entries.value),base=version.value;
  inflight=true;status.value='saving';
  let complete;
  inflightCompletion=new Promise(resolve=>{complete=resolve;});
  try{
   const result=await api.saveQueue(selectedDate,base,sent,selectedCredential);if(!valid(epoch)||selectedDate!==date.value||selectedCredential!==credentialId.value)return;
   if(!Number.isSafeInteger(result.queue?.version)||result.queue.version<base||result.queue.version>base+1)throw new Error('invalid_queue_response');
   const confirmed=queueEntries(result.queue);
   if(fingerprint(confirmed)!==fingerprint(sent))throw new Error('invalid_queue_response');
   version.value=result.queue.version;lastSaved=fingerprint(confirmed);dirty.value=fingerprint(entries.value)!==lastSaved;status.value=dirty.value?'pending':'ready';remember();refreshList();
  }catch(e){
   if(!valid(epoch)||selectedDate!==date.value||selectedCredential!==credentialId.value)return;
   blocked.value=true;status.value=e?.status===409?'conflict':'error';
   error.value=e?.status===409?'版本冲突：本地队列已保留，自动保存已暂停。':e?.status===400?'队列未保存，请核对时间和场地。':'保存结果未确认，本地队列已保留，请读取最新版本核对。';remember();
  }finally{if(valid(epoch)){inflight=false;if(dirty.value&&!blocked.value)schedule();}complete();}
 }
 async function inspectLatest(){
  if(!authenticated()||!credentialId.value)return;const epoch=generation,selectedDate=date.value,selectedCredential=credentialId.value;
  try{const result=await api.queue(selectedDate,selectedCredential);if(!valid(epoch)||selectedDate!==date.value||selectedCredential!==credentialId.value)return;
   latest.value=result.queue;
   if(fingerprint(queueEntries(result.queue))===fingerprint(entries.value)){
    version.value=result.queue?.version||0;lastSaved=fingerprint(entries.value);dirty.value=false;blocked.value=false;error.value='';status.value='ready';latest.value=undefined;remember();refreshList();
   }
  }catch{if(valid(epoch)&&selectedCredential===credentialId.value)error.value='最新版本读取失败，本地内容已保留。';}
 }
 function adoptLatest(){if(latest.value===undefined)return;entries.value=queueEntries(latest.value);version.value=latest.value?.version||0;lastSaved=fingerprint(entries.value);dirty.value=false;blocked.value=false;error.value='';status.value='ready';latest.value=undefined;remember();refreshList();}
 function saveLocalAgainstLatest(){if(latest.value===undefined||!authenticated())return;version.value=latest.value?.version||0;lastSaved=fingerprint(queueEntries(latest.value));blocked.value=false;error.value='';latest.value=undefined;dirty.value=fingerprint(entries.value)!==lastSaved;remember();if(dirty.value)schedule();else status.value='ready';}
 async function showHistory(selectedDate,selectedCredential=credentialId.value,more=false){
  if(historyLoading.value||(more&&!historyCursor.value))return;
  const epoch=generation,seq=++historySequence;historyError.value='';historyLoading.value=true;
  if(!more){history.value=null;historyCursor.value=null;historySelection={selectedDate,selectedCredential};}
  try{const result=await api.queueRevisions(selectedDate,selectedCredential,more?historyCursor.value:undefined);if(valid(epoch)&&seq===historySequence){history.value=more?[...history.value,...result.revisions]:result.revisions;historyCursor.value=result.next_before_version||null;}}
  catch{if(valid(epoch)&&seq===historySequence)historyError.value='历史读取失败。';}
  finally{if(valid(epoch)&&seq===historySequence)historyLoading.value=false;}
 }
 const loadMoreHistory=()=>historySelection&&showHistory(historySelection.selectedDate,historySelection.selectedCredential,true);
 function closeHistory(){historySequence++;history.value=null;historyCursor.value=null;historyLoading.value=false;historySelection=null;}
 watch(date,()=>load());
 watch(isActive,active=>{if(active)load();});
 watch(credentialId,()=>{
  remember(activeCredentialId);activeCredentialId=credentialId.value;generation++;loadSequence++;listSequence++;historySequence++;clearTimeout(timer);inflight=false;
  entries.value=[];queues.value=[];version.value=0;dirty.value=false;blocked.value=false;latest.value=undefined;closeHistory();historyError.value='';error.value='';lastSaved='[]';status.value='idle';
  if(credentialId.value){load();refreshList();}
 },{flush:'sync'});
 watch(()=>[session?.status,session?.user?.user_id,session?.csrfToken,session?.invalidationEpoch],()=>{
  remember();generation++;loadSequence++;listSequence++;clearTimeout(timer);inflight=false;queues.value=[];closeHistory();latest.value=undefined;
  if(!authenticated()){status.value='suspended';return;}
  const newOwner=session.user.user_id;if(owner!==newOwner){drafts=rememberedByUser.get(newOwner)||new Map();rememberedByUser.set(newOwner,drafts);entries.value=[];dirty.value=false;version.value=0;lastSaved='[]';}
  owner=newOwner;load();refreshList();
 },{immediate:true,flush:'sync'});
 function warnBeforeUnload(event){if(dirty.value){event.preventDefault();event.returnValue='';}}
 if(typeof window!=='undefined')window.addEventListener('beforeunload',warnBeforeUnload);
 onUnmounted(()=>{remember();alive=false;generation++;clearTimeout(timer);if(typeof window!=='undefined')window.removeEventListener('beforeunload',warnBeforeUnload);});
 return reactive({entries,queues,version,status,statusText,error,blocked,dirty,latest,locked,dateLocked,history,historyError,historyCursor,historyLoading,loadMoreHistory,closeHistory,credentialId,change,inspectLatest,adoptLatest,saveLocalAgainstLatest,showHistory,refreshList,load,flush});
}
