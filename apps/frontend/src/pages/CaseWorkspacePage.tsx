import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, authHeaders, formatApiError } from '../api/client';
import type { CaseHypothesis, CaseWorkspace, WorkspaceAssessment, WorkspaceEntity } from '../api/types';
import { useApi } from '../hooks/useApi';
import { useLive } from '../hooks/useLive';
import { formatDateTime, formatPercent, shortId } from '../lib/format';
import { Badge } from '../components/Badge';
import { EmptyState, ErrorState, LoadingState } from '../components/States';
import { EvidenceDrawer } from '../components/EvidenceDrawer';
import { EvidenceForm } from '../components/EvidenceForm';
import { GraphView } from '../components/GraphView';
import type { GraphEdge, GraphNode } from '../components/GraphView';
import { AssessmentPanel } from '../components/workspace/AssessmentPanel';
import { TimelinePanel } from '../components/workspace/TimelinePanel';

type Tab='overview'|'evidence'|'network'|'timeline'|'assessment'|'notes';
const tabs: Array<{id:Tab;label:string}>=[{id:'overview',label:'Overview'},{id:'evidence',label:'Evidence'},{id:'network',label:'Network'},{id:'timeline',label:'Timeline'},{id:'assessment',label:'Assessment'},{id:'notes',label:'Notes'}];
const tone=(value:number|null|undefined)=> value===null||value===undefined?'neutral':value>=.75?'ok':value>=.5?'warn':'danger';
async function downloadReport(url:string, filename:string){ const response=await fetch(url,{headers:authHeaders()}); if(!response.ok) throw new Error(`Export failed (${response.status})`); const blob=await response.blob(); const href=URL.createObjectURL(blob); const anchor=document.createElement('a'); anchor.href=href; anchor.download=filename; anchor.click(); URL.revokeObjectURL(href); }

function Metric({value,label,sub}:{value:string|number;label:string;sub?:string}){return <div className="invest-metric"><strong>{value}</strong><span>{label}</span>{sub&&<small>{sub}</small>}</div>}
function Overview({data,assessment,onTab}:{data:CaseWorkspace;assessment:WorkspaceAssessment|undefined;onTab:(tab:Tab)=>void}){
  const nodes=data.entities.slice().sort((a,b)=>b.confidence-a.confidence).slice(0,18).map((e:WorkspaceEntity):GraphNode=>({id:e.entity_id,label:e.surface_form,type:e.type,confidence:e.confidence}));
  const visible=new Set(nodes.map(n=>n.id));
  const edges=data.relationships.filter(r=>visible.has(r.subject_entity_id)&&visible.has(r.object_entity_id)).slice(0,36).map((r):GraphEdge=>({source:r.subject_entity_id,target:r.object_entity_id,label:r.type,tone:r.confidence>=.5?'ok':'danger',confidence:r.confidence}));
  return <>
    <section className="invest-hero-grid">
      <div className="invest-hero-copy"><span className="eyebrow">Investigation picture</span><h2>What the evidence currently supports.</h2><p>{data.case.description||'No case description recorded.'}</p><div className="invest-hero-meta"><span>Updated {formatDateTime(data.case.updated_at)}</span><span>Last activity {formatDateTime(data.activity[0]?.occurred_at??null)}</span><span className="live-inline"><i/> live synchronized</span></div></div>
      <div className="invest-score"><span className="eyebrow">Attribution confidence</span><strong>{assessment?formatPercent(assessment.calibrated_confidence??assessment.raw_score):'—'}</strong><div className="score-track"><i style={{width:`${Math.max(0,Math.min(100,(assessment?.calibrated_confidence??assessment?.raw_score??0)*100))}%`}}/></div><small>{assessment?.model_id??'No assessment available'}</small></div>
    </section>
    <section className="invest-metrics"><Metric value={data.counts.evidence} label="Evidence" sub="ledger records"/><Metric value={data.counts.entities} label="Entities" sub="extracted objects"/><Metric value={data.counts.relationships} label="Relationships" sub="observed links"/><Metric value={data.counts.assessments} label="Assessments" sub="model outputs"/></section>
    <section className="invest-main-grid">
      <div className="invest-panel invest-network-preview"><div className="invest-panel-head"><div><span className="eyebrow">Relationship field</span><h3>Evidence-linked entity network</h3></div><button className="text-action" onClick={()=>onTab('network')}>Open network →</button></div>{nodes.length?<GraphView nodes={nodes} edges={edges} label={`Relationship network for ${data.case.name}`} onSelectNode={()=>onTab('network')}/>:<EmptyState title="No entities" message="No extracted entities are available for this investigation."/>}</div>
      <div className="invest-side-stack">
        <div className="invest-panel"><div className="invest-panel-head"><div><span className="eyebrow">Evidence posture</span><h3>Signal composition</h3></div><button className="text-action" onClick={()=>onTab('assessment')}>Assessment →</button></div>{assessment?<div className="signal-bars">{Object.entries(assessment.signals).slice(0,7).map(([key,val])=><div key={key}><span>{key.replaceAll('_',' ')}</span><b>{Math.round(val*100)}%</b><i><em style={{width:`${Math.max(0,Math.min(100,val*100))}%`}}/></i></div>)}</div>:<p className="hint">No model signal decomposition is available.</p>}</div>
        <div className="invest-panel"><div className="invest-panel-head"><div><span className="eyebrow">Recent activity</span><h3>Investigation trail</h3></div></div><div className="mini-activity">{data.activity.slice(0,6).map(row=><div key={row.seq}><i/><div><strong>{String(row.payload.message??row.action)}</strong><small>{formatDateTime(row.occurred_at)}</small></div></div>)}</div></div>
      </div>
    </section>
    <section className="invest-bottom-grid"><div className="invest-panel"><div className="invest-panel-head"><div><span className="eyebrow">Leading entities</span><h3>Objects carrying the investigation</h3></div><button className="text-action" onClick={()=>onTab('network')}>Explore →</button></div><div className="entity-rail">{data.entities.slice().sort((a,b)=>b.confidence-a.confidence).slice(0,6).map((e,i)=><button key={e.entity_id} onClick={()=>onTab('network')}><span>{String(i+1).padStart(2,'0')}</span><strong>{e.surface_form}</strong><small>{e.type} · {formatPercent(e.confidence)}</small></button>)}</div></div><div className="invest-panel"><div className="invest-panel-head"><div><span className="eyebrow">Integrity</span><h3>Chain-of-custody snapshot</h3></div></div><div className="integrity-list"><div><span>Evidence records</span><b>{data.evidence.length}</b></div><div><span>Hashed artifacts</span><b>{data.evidence.filter(e=>Boolean(e.sha256)).length}</b></div><div><span>Independent groups</span><b>{new Set(data.evidence.map(e=>e.independence_group)).size}</b></div><div><span>Contradictory items</span><b>{assessment?.contradictory_evidence_ids.length??0}</b></div></div></div></section>
  </>;
}

export function CaseWorkspacePage(){
  const {caseId=''}=useParams(); const {snapshot}=useLive();
  const resource=useApi<CaseWorkspace>(caseId?`/api/v1/cases/${encodeURIComponent(caseId)}/workspace`:null);
  const hypotheses=useApi<CaseHypothesis[]>(caseId?`/api/v1/cases/${encodeURIComponent(caseId)}/hypotheses`:null);
  const [tab,setTab]=useState<Tab>('overview'); const [openEvidence,setOpenEvidence]=useState<string|null>(null); const [note,setNote]=useState(''); const [notes,setNotes]=useState<Array<{note_id:string;body:string;created_at:string|null}>>([]); const [selectedCase,setSelectedCase]=useState<CaseWorkspace|null>(null); const [noteBusy,setNoteBusy]=useState(false); const [noteError,setNoteError]=useState<string|null>(null);
  useEffect(()=>{if(snapshot?.server_time) resource.reload();},[snapshot?.server_time]);
  useEffect(()=>{if(resource.data)setSelectedCase(resource.data);},[resource.data]);
  const data=selectedCase; const assessment=data?.assessments[0];
  useEffect(()=>{if(!caseId)return; void api.listNotes(caseId).then(setNotes).catch(()=>undefined);},[caseId]);
  const graphData=useMemo(()=>{if(!data)return {nodes:[] as GraphNode[],edges:[] as GraphEdge[]};const nodes=data.entities.slice(0,28).map(e=>({id:e.entity_id,label:e.surface_form,type:e.type,confidence:e.confidence}));const ids=new Set(nodes.map(n=>n.id));const edges=data.relationships.filter(r=>ids.has(r.subject_entity_id)&&ids.has(r.object_entity_id)).slice(0,60).map(r=>({source:r.subject_entity_id,target:r.object_entity_id,label:r.type,tone:r.confidence>=.5?'ok':'danger' as const,confidence:r.confidence}));return {nodes,edges};},[data]);
  if(!caseId)return <div className="page-stack"><EmptyState title="No case selected" message="Pick an investigation from Cases."/></div>;
  if(resource.error)return <div className="page-stack"><ErrorState message={resource.error} onRetry={resource.reload}/></div>;
  if(!data)return <div className="page-stack"><LoadingState label="Loading investigation workspace…"/></div>;
  const saveNote=async()=>{if(!note.trim())return;setNoteBusy(true);setNoteError(null);try{const created=await api.createNote(caseId,{body:note.trim()});setNotes(v=>[created,...v]);setNote('');}catch(e){setNoteError(formatApiError(e))}finally{setNoteBusy(false)}};
  return <div className="page-stack workspace-page-v3">
    <header className="invest-header"><div><div className="breadcrumbs"><Link to="/cases">Cases</Link><span>›</span><span>{data.case.name}</span></div><div className="invest-title"><span className="case-code">CASE {shortId(caseId,8).toUpperCase()}</span><h1>{data.case.name}</h1><Badge tone={tone(data.case.severity==='critical'?1:data.case.severity==='high'?.75:.45) as 'ok'|'warn'|'danger'|'neutral'}>{data.case.status.replace('_',' ')}</Badge></div><p>{data.case.tags.length?data.case.tags.join('  ·  '):'Investigation workspace'}</p></div><div className="invest-actions"><span className="live-inline"><i/> {snapshot?'LIVE':'SYNCING'}</span><button className="button" onClick={()=>void downloadReport(api.reportExportUrl(caseId,'pdf'),`${data.case.name.replace(/\W+/g,'-').toLowerCase()}.pdf`)}>Export report</button><button className="button button--dark" onClick={()=>setTab('assessment')}>Review assessment</button></div></header>
    <nav className="invest-tabs" aria-label="Investigation views">{tabs.map(t=><button key={t.id} className={tab===t.id?'is-active':''} onClick={()=>setTab(t.id)}>{t.label}{t.id==='evidence'&&<small>{data.counts.evidence}</small>}{t.id==='network'&&<small>{data.counts.relationships}</small>}</button>)}</nav>
    {tab==='overview'&&<Overview data={data} assessment={assessment} onTab={setTab}/>} 
    {tab==='evidence'&&<section className="invest-panel invest-tab-panel"><div className="invest-panel-head"><div><span className="eyebrow">Evidence ledger</span><h3>Collected records</h3></div><button className="text-action" onClick={resource.reload}>Refresh</button></div>{openEvidence&&<EvidenceDrawer evidenceId={openEvidence} onClose={()=>setOpenEvidence(null)} onLoaded={()=>undefined} onOpenEvidence={setOpenEvidence}/>}<div className="evidence-grid">{data.evidence.slice(0,120).map(row=><button key={row.evidence_id} className="evidence-card" onClick={()=>setOpenEvidence(row.evidence_id)}><div><span>{row.source_type}</span><small>{formatDateTime(row.observed_at??row.collected_at)}</small></div><strong>{shortId(row.evidence_id,12)}</strong><p>{row.metadata?.title?String(row.metadata.title):'Evidence artifact'}</p><footer><span>REL {formatPercent(row.reliability)}</span><span className="mono">{shortId(row.sha256,10)}</span></footer></button>)}</div><EvidenceForm caseId={caseId} onCreated={resource.reload}/></section>}
    {tab==='network'&&<section className="invest-panel invest-tab-panel"><div className="invest-panel-head"><div><span className="eyebrow">Network analysis</span><h3>Semantic relationship graph</h3></div><span className="surface-meta">{graphData.nodes.length} nodes · {graphData.edges.length} links</span></div><GraphView nodes={graphData.nodes} edges={graphData.edges} label={`Network for ${data.case.name}`} onSelectNode={()=>undefined}/></section>}
    {tab==='timeline'&&<TimelinePanel workspace={data} onRefresh={resource.reload}/>} 
    {tab==='assessment'&&<AssessmentPanel workspace={data} hypotheses={hypotheses.data??[]} onSelectEvidence={(id)=>{setOpenEvidence(id);setTab('evidence')}}/>}
    {tab==='notes'&&<section className="invest-panel invest-tab-panel"><div className="invest-panel-head"><div><span className="eyebrow">Analyst record</span><h3>Notes & observations</h3></div><span className="surface-meta">{notes.length} notes</span></div><div className="note-compose"><textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Record an observation, contradiction, lead or next verification step…"/><button className="button button--dark" disabled={noteBusy} onClick={()=>void saveNote()}>{noteBusy?'Saving…':'Add note'}</button></div>{noteError&&<p className="status status--error">{noteError}</p>}<div className="notes-v3">{notes.map(n=><article key={n.note_id}><p>{n.body}</p><small>{formatDateTime(n.created_at)}</small></article>)}</div></section>}
  </div>;
}
