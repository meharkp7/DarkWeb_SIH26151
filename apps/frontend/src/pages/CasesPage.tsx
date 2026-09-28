import { Link } from 'react-router-dom';
import { useState } from 'react';
import { api, formatApiError } from '../api/client';
import type { CaseSummary } from '../api/types';
import { useApi } from '../hooks/useApi';

export function CasesPage(){
 const {data,reload,loading,error}=useApi<CaseSummary[]>('/api/v1/dashboard/cases');
 const [query,setQuery]=useState(''); const [creating,setCreating]=useState(false); const [name,setName]=useState(''); const [message,setMessage]=useState('');
 const rows=(data??[]).filter(x=>x.name.toLowerCase().includes(query.toLowerCase()));
 const create=async()=>{ if(!name.trim())return; setCreating(true); try{const c=await api.createCase({name:name.trim(),description:'New authorized investigation'}); setMessage(`Created ${c.name}`); setName(''); reload();}catch(e){setMessage(formatApiError(e));}finally{setCreating(false);} };
 return <div className="page-stack"><header className="hero-head"><div><span className="eyebrow">Investigations</span><h1>Cases</h1><p>One workspace per investigation. Evidence, network, timeline and assessment stay together.</p></div><div className="hero-actions"><button className="button button--dark" onClick={()=>void create()} disabled={creating}>{creating?'Creating…':'+ New investigation'}</button></div></header>
 <div className="toolbar"><div className="search-field"><span>⌕</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search investigations…" /></div><div className="toolbar-note">{rows.length} visible · live from PostgreSQL</div></div>
 {error && <div className="inline-error">{error}</div>}{message&&<div className="toast-inline">{message}</div>}
 <section className="case-list">{rows.map(item=><Link className="case-row" to={`/cases/${item.case_id}`} key={item.case_id}><div className="case-row__identity"><span className="case-icon">◇</span><div><h3>{item.name}</h3><p>{item.description}</p></div></div><div className="case-row__metrics"><span><b>{item.counts.evidence}</b> evidence</span><span><b>{item.counts.entities}</b> entities</span><span><b>{item.counts.relationships}</b> links</span><span className={`pill pill--${item.status}`}>{item.status.replace('_',' ')}</span></div><span className="case-row__arrow">→</span></Link>)}{!loading&&rows.length===0&&<div className="empty-state">No investigations match this search.</div>}</section>
 </div>;
}
