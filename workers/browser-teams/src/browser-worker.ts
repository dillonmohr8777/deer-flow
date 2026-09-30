import { localBrowser, Stagehand, type ClientLLM, type Page, type StagehandBrowser, StagehandRuntimeIncompatibleError } from '@browserbasehq/stagehand';
import {readFileSync} from 'node:fs';
import { z } from 'zod';
import { emit,lines,receive, type ModelResult } from './protocol.js';

const identity=z.string().regex(/^[A-Za-z0-9_-]{1,128}$/);
export const snapshotSchema=z.object({title:z.string().max(200),final_url:z.string().max(2048),text:z.string().max(60000)}).passthrough();
export const openSchema=z.object({type:z.literal('open'),version:z.literal(1),lease_id:identity,deadline_ms:z.number().int().positive(),connect_url:z.string().max(4096),session_id:z.string().uuid(),api_key:z.string().min(10).max(1024),ai_enabled:z.boolean()}).strict();
export const operationSchema=z.discriminatedUnion('op',[
 z.object({op:z.literal('navigate'),lease_id:identity,page:snapshotSchema}).strict(),
 z.object({op:z.literal('observe'),lease_id:identity,instruction:z.string().min(1).max(3000)}).strict(),
 z.object({op:z.literal('extract'),lease_id:identity,instruction:z.string().min(1).max(3000)}).strict(),
 z.object({op:z.literal('capture'),lease_id:identity}).strict(),
 z.object({op:z.literal('close'),lease_id:identity}).strict()
]);
const extraction=z.object({title:z.string().max(200),summary:z.string().max(2000),claims:z.array(z.object({claim:z.string().max(500),quote:z.string().max(1000)})).max(8)});
export type OpenFrame=z.infer<typeof openSchema>;
export function validateOpen(value:unknown):OpenFrame {
 const frame=openSchema.parse(value);const url=new URL(frame.connect_url);
 const querySessions=url.searchParams.getAll('sessionId');
 const authority=frame.connect_url.split('/')[2]?.split(/[?#]/)[0]??'';
 if(url.protocol!=='wss:'||url.port&&url.port!=='443'||url.username||url.password||authority.includes('@')||frame.connect_url.includes('#')||!['connect.browserbase.com','connect.usw2.browserbase.com'].includes(url.hostname)||(querySessions.length>0&&(querySessions.length!==1||querySessions[0]!==frame.session_id)))throw new Error('invalid_provider_endpoint');
 const remaining=frame.deadline_ms-Date.now();if(remaining<1000||remaining>180000)throw new Error('invalid_deadline');
 return frame;
}
export function snapshotDocument(page:z.infer<typeof snapshotSchema>):string {
 const escape=(value:string)=>value.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
 return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'none\'; style-src \'unsafe-inline\'; form-action \'none\'; base-uri \'none\'"><style>body{margin:48px;color:#141414;background:white;font:20px/1.55 system-ui}pre{white-space:pre-wrap;font:inherit}p{overflow-wrap:anywhere}</style><title>'+escape(page.title)+'</title></head><body><p>Public source text snapshot · MomoBot</p><h1>'+escape(page.title)+'</h1><p>'+escape(page.final_url)+'</p><pre>'+escape(page.text.slice(0,24000))+'</pre></body></html>';
}

export function classifyBrowserFailure(error:unknown):string {
 const message=error instanceof Error?error.message:'';
 const fixed=['browser_transport_failed','stagehand_extension_unavailable','stagehand_extension_inspection_failed','stagehand_runtime_incompatible','stagehand_operation_timeout','stagehand_initialization_failed','browser_snapshot_render_failed','browser_snapshot_capture_failed','stagehand_observation_failed','stagehand_extraction_failed','browser_cleanup_failed'];
 if(fixed.includes(message))return message;
 if(error instanceof StagehandRuntimeIncompatibleError)return 'stagehand_runtime_incompatible';
 if(message.startsWith('Stagehand extension is not installed')||message.startsWith('Stagehand extension is installed'))return 'stagehand_extension_unavailable';
 if(error instanceof Error&&(error.name==='AbortError'||error.name==='TimeoutError'||message.includes('timed out')))return 'stagehand_operation_timeout';
 return 'browser_operation_failed';
}

type BrowserPhaseCode='browser_transport_failed'|'stagehand_initialization_failed'|'browser_snapshot_render_failed'|'browser_snapshot_capture_failed'|'stagehand_observation_failed'|'stagehand_extraction_failed'|'browser_cleanup_failed';
export async function withBrowserPhase<T>(phase:BrowserPhaseCode,operation:()=>Promise<T>):Promise<T>{
 try{return await operation();}catch(error){const code=classifyBrowserFailure(error);throw new Error(code==='browser_operation_failed'?phase:code);}
}

/** CDP-only attach: never re-fetch a session or create/upload a provider resource. */
export async function connectOwnedBrowser(frame:OpenFrame,dependencies:{socket?:(url:string)=>WebSocket;connect?:(options:{cdpUrl:string;extensionId:string})=>Promise<StagehandBrowser>}={}):Promise<StagehandBrowser>{
 const manifest=z.object({name:z.literal('Stagehand Runtime'),version:z.string().min(1)}).passthrough().parse(JSON.parse(readFileSync(new URL('../../node_modules/@browserbasehq/stagehand/dist/extension/manifest.json',import.meta.url),'utf8')));
 const remaining=frame.deadline_ms-Date.now();if(remaining<1000)throw new Error('stagehand_operation_timeout');
 const socket=(dependencies.socket??(url=>new WebSocket(url)))(frame.connect_url);
 const extensionId=await new Promise<string>((resolve,reject)=>{
  let finished=false;
  const finish=(error?:Error,id?:string)=>{if(finished)return;finished=true;clearTimeout(timer);if(error){try{socket.close();}catch{/* The creating service still owns remote release. */}reject(error);}else resolve(id!);};
  const timer=setTimeout(()=>finish(new Error('browser_transport_failed')),Math.min(10000,remaining));
  socket.addEventListener('error',()=>finish(new Error('browser_transport_failed')));
  socket.addEventListener('close',()=>finish(new Error('browser_transport_failed')));
  socket.addEventListener('open',()=>{try{socket.send(JSON.stringify({id:1,method:'Extensions.getExtensions',params:{}}));}catch{finish(new Error('browser_transport_failed'));}},{once:true});
  socket.addEventListener('message',event=>{
   try{
    if(typeof event.data!=='string'||Buffer.byteLength(event.data)>65536)throw new Error('stagehand_extension_inspection_failed');
    const reply=JSON.parse(event.data);if(reply.id!==1)return;
    if(reply.error)throw new Error('stagehand_extension_inspection_failed');
    const extensions=z.array(z.object({id:z.string().regex(/^[a-p]{32}$/),name:z.string(),version:z.string(),enabled:z.boolean()}).passthrough()).max(20).parse(reply.result?.extensions);
    const installed=extensions.filter(extension=>extension.name===manifest.name&&extension.version===manifest.version&&extension.enabled);
    if(installed.length!==1)throw new Error('stagehand_extension_unavailable');
    finish(undefined,installed[0]!.id);
   }catch(error){finish(new Error(error instanceof Error&&error.message==='stagehand_extension_unavailable'?'stagehand_extension_unavailable':'stagehand_extension_inspection_failed'));}
  });
 });
 // Explicit Chrome extension ID avoids SDK's unpacked-extension upload path.
 // localBrowser.connect does not launch Chrome. Its pinned close implementation
 // sends Browser.close, so only the protected service-owned session is admitted;
 // the creating service independently releases and verifies terminal readback.
 // keepAlive=false ends Browserbase sessions when the final CDP connection
 // closes. Retain this inspection connection until the SDK attachment exists.
 try{return await withBrowserPhase('browser_transport_failed',()=> (dependencies.connect??(options=>localBrowser.connect(options)))({cdpUrl:frame.connect_url,extensionId}));}
 finally{try{socket.close();}catch{/* The creating service still owns remote release. */}}
}

export class BrowserModelRelay {
 count=0;
 constructor(readonly frame:OpenFrame,readonly iterator:AsyncIterator<string>){}
 readonly generate:ClientLLM['generate']=async(params)=>{
  if(!this.frame.ai_enabled||++this.count>3||Date.now()>=this.frame.deadline_ms)throw new Error('model_call_limit');
  if(!params.responseFormat||params.responseFormat.type!=='json_schema')throw new Error('structured_output_required');
  const messages:{role:'system'|'assistant'|'user';content:string}[]=[];
  if(params.systemPrompt)messages.push({role:'system',content:params.systemPrompt});
  for(const message of params.messages){
   const parts=Array.isArray(message.content)?message.content:[message.content];
   const content=parts.map(part=>{if(part.type!=='text')throw new Error('nontext_browser_input_disabled');return part.text;}).join('\n');
   messages.push({role:message.role,content});
  }
  const call_id=`${this.frame.lease_id}_stagehand_${this.count}`;
  emit({type:'model_request',version:1,lease_id:this.frame.lease_id,call_id,messages,output_schema:params.responseFormat.schema});
  const raw=await receive(this.iterator);
  const reply=z.object({type:z.literal('model_result'),version:z.literal(1),lease_id:z.literal(this.frame.lease_id),call_id:z.literal(call_id),result:z.object({output:z.unknown(),model:z.literal('gpt-6.1-sol'),effort:z.enum(['low','medium','high']),usage:z.object({input_tokens:z.number().int().nonnegative(),output_tokens:z.number().int().nonnegative(),cost:z.number().nonnegative().nullable()})}).passthrough()}).strict().parse(raw);
  const result=reply.result as ModelResult;
  return {role:'assistant',content:{type:'text',text:JSON.stringify(result.output)},outputFormat:'json_schema',structuredContent:z.json().parse(result.output),stopReason:'endTurn',usage:{inputTokens:result.usage.input_tokens,outputTokens:result.usage.output_tokens,totalTokens:result.usage.input_tokens+result.usage.output_tokens}};
 };
}

export class SnapshotBrowserBroker {
 page:Page|undefined;
 navigationCount=0;
 closed=false;
 constructor(readonly frame:OpenFrame,readonly stagehand:Stagehand,readonly browser:StagehandBrowser){}
 async operation(value:unknown):Promise<Record<string,unknown>>{
  const command=operationSchema.parse(value);
  if(command.lease_id!==this.frame.lease_id||this.closed||Date.now()>=this.frame.deadline_ms)throw new Error('lease_rejected');
  const timeout=Math.min(45000,Math.max(1,this.frame.deadline_ms-Date.now()));
  switch(command.op){
   case 'navigate':{
    if(++this.navigationCount>3)throw new Error('page_limit');
    await withBrowserPhase('browser_snapshot_render_failed',async()=>{
     if(this.page)await this.page.close();
     // Literal code constructs only escaped inert data: documents. No website navigation.
     this.page=await this.browser.context.newPage('data:text/html;base64,'+Buffer.from(snapshotDocument(command.page)).toString('base64'));
     await this.page.setViewportSize(1280,900);
    });
    return {page_index:this.navigationCount-1,mode:'public_text_snapshot'};
   }
   case 'observe':{
    if(!this.page||!this.frame.ai_enabled)throw new Error('browser_ai_not_admitted');
    const result=await withBrowserPhase('stagehand_observation_failed',()=>this.stagehand.observe(command.instruction,{page:this.page!,cache:false,timeout}));
    return {data:result.data,metadata:result.metadata,mode:'stagehand_observe_public_snapshot'};
   }
   case 'extract':{
    if(!this.page||!this.frame.ai_enabled)throw new Error('browser_ai_not_admitted');
    const result=await withBrowserPhase('stagehand_extraction_failed',()=>this.stagehand.extract(command.instruction,extraction,{page:this.page!,cache:false,timeout}));
    return {data:result.data,metadata:result.metadata,mode:'stagehand_extract_public_snapshot'};
   }
   case 'capture':{
    if(!this.page)throw new Error('page_missing');
    const png=await withBrowserPhase('browser_snapshot_capture_failed',()=>this.page!.screenshot({type:'png',fullPage:false}));
    if(png.length>4194304||!Buffer.from(png.subarray(0,8)).equals(Buffer.from([137,80,78,71,13,10,26,10])))throw new Error('invalid_screenshot');
    return {png_base64:Buffer.from(png).toString('base64'),bytes:png.length,mode:'public_text_snapshot'};
   }
   case 'close':await withBrowserPhase('browser_cleanup_failed',()=>this.close());return {closed:true};
  }
 }
 async close():Promise<void>{
  if(this.closed)return;this.closed=true;
  try{if(this.page)await this.page.close();}finally{try{await this.stagehand.close();}finally{await this.browser.close();}}
 }
}

let protocolLease:string|undefined;
async function main(){
 const iterator=lines();const frame=validateOpen(await receive(iterator));
 protocolLease=frame.lease_id;
 const timer=setTimeout(()=>process.exit(2),Math.max(1,frame.deadline_ms-Date.now()));
 const relay=new BrowserModelRelay(frame,iterator);
 let broker:SnapshotBrowserBroker|undefined;let browser:StagehandBrowser|undefined;let failed=false;
 try{
  browser=await connectOwnedBrowser(frame);
  const stagehand=await withBrowserPhase('stagehand_initialization_failed',()=>Stagehand.create({browser:browser!,cache:false,model:{generate:relay.generate},logging:{level:'off'}}));
  broker=new SnapshotBrowserBroker(frame,stagehand,browser);
  emit({type:'opened',version:1,lease_id:frame.lease_id});
  while(!broker.closed){
   const command=operationSchema.parse(await receive(iterator));
   const result=await broker.operation(command);
   emit({type:'operation_result',version:1,lease_id:frame.lease_id,op:command.op,result},command.op==='capture'?6291456:262144);
  }
 }catch(error){failed=true;throw error;}finally{
  clearTimeout(timer);
  // Preserve the original operation failure if cleanup also fails. The parent
  // independently releases and verifies the exact owned provider session.
  try{await withBrowserPhase('browser_cleanup_failed',async()=>{if(broker)await broker.close();else if(browser)await browser.close();});}catch(error){if(!failed)throw error;}
 }
}
if(process.argv[1]?.endsWith('browser-worker.js')){
 console.log=()=>{};console.info=()=>{};console.warn=()=>{};console.error=()=>{};
 main().then(()=>process.exit(0)).catch((error)=>{
  const code=classifyBrowserFailure(error);
  emit({type:'error',version:1,lease_id:protocolLease,code});process.exit(1);
 });
}
