import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ClientLLMSchema, type Stagehand, type StagehandBrowser, type Page} from '@browserbasehq/stagehand';
import {BrowserModelRelay,SnapshotBrowserBroker,validateOpen,snapshotDocument,operationSchema,connectOwnedBrowser,classifyBrowserFailure,withBrowserPhase,type OpenFrame} from '../src/browser-worker.js';
import {extensionManifest} from '../src/extension-setup.js';

const session='12345678-1234-4234-8234-123456789abc';
function frame(overrides:Record<string,unknown>={}):OpenFrame{return validateOpen({type:'open',version:1,lease_id:'owner_run_lease',deadline_ms:Date.now()+60000,connect_url:`wss://connect.browserbase.com?sessionId=${session}&apiKey=opaque`,session_id:session,api_key:'offline-fake-key',ai_enabled:true,...overrides});}

test('reject nonprovider endpoints, foreign sessions, invalid deadlines and arbitrary code',()=>{
 for(const overrides of [{connect_url:`wss://localhost?sessionId=${session}`},{connect_url:`wss://evil.browserbase.com?sessionId=${session}`},{connect_url:`wss://user:password@connect.browserbase.com?sessionId=${session}`},{connect_url:`wss://@connect.browserbase.com`},{connect_url:`wss://connect.browserbase.com:444`},{connect_url:`wss://connect.browserbase.com#fragment`},{connect_url:`https://connect.browserbase.com?sessionId=${session}`},{connect_url:`wss://connect.browserbase.com?sessionId=other`},{connect_url:`wss://connect.browserbase.com?sessionId=`},{connect_url:`wss://connect.browserbase.com?sessionId=${session}&sessionId=${session}`},{session_id:'invalid'},{deadline_ms:Date.now()-1},{deadline_ms:Date.now()+200000}])assert.throws(()=>frame(overrides));
 for(const op of ['act','evaluate','run','login'])assert.equal(operationSchema.safeParse({op,lease_id:'owner_run_lease',code:'arbitrary()'}).success,false);
 assert.equal(operationSchema.safeParse({op:'navigate',lease_id:'owner_run_lease',url:'http://127.0.0.1'}).success,false);
});

test('opaque provider URL stays bound to explicit creation session receipt',()=>{
 for(const connect_url of ['wss://connect.browserbase.com?apiKey=synthetic-opaque','wss://connect.usw2.browserbase.com/opaque-fixture?token=synthetic-opaque',`wss://connect.browserbase.com:443?sessionId=${session}`]){
  const owned=frame({connect_url});assert.equal(owned.session_id,session);assert.equal(owned.connect_url,connect_url);
 }
});

test('source snapshots are escaped inert CSP documents',()=>{
 const doc=snapshotDocument({title:'<script>alert(1)</script>',final_url:'https://example.com/?x=<img>',text:'<img src="http://private"><form action="https://evil"> & text'});
 assert.ok(doc.includes('&lt;script&gt;'));
 assert.ok(doc.includes("default-src 'none'"));
 assert.ok(doc.includes("form-action 'none'"));
 assert.equal(doc.includes('<img'),false);
 assert.equal(doc.includes('<form'),false);
});

test('typed broker dispatches real Stagehand APIs with cache disabled and lease fencing',async()=>{
 const calls:string[]=[];const options:unknown[]=[];
 const page={setViewportSize:async()=>{},close:async()=>{calls.push('page.close');},screenshot:async()=>new Uint8Array([137,80,78,71,13,10,26,10])} as unknown as Page;
 const browser={context:{newPage:async(url:string)=>{assert.ok(url.startsWith('data:text/html;base64,'));calls.push('navigate');return page;}},close:async()=>{calls.push('browser.close');}} as unknown as StagehandBrowser;
 const stagehand={observe:async(_instruction:string,opts:unknown)=>{calls.push('observe');options.push(opts);return {data:[],metadata:{cache:{status:'DISABLED'}}};},extract:async(_instruction:string,_schema:unknown,opts:unknown)=>{calls.push('extract');options.push(opts);return {data:{title:'Example',summary:'Evidence',claims:[]},metadata:{cache:{status:'DISABLED'}}};},close:async()=>{calls.push('stagehand.close');}} as unknown as Stagehand;
 const broker=new SnapshotBrowserBroker(frame(),stagehand,browser);
 await assert.rejects(()=>broker.operation({op:'navigate',lease_id:'other',page:{title:'X',final_url:'https://example.com',text:'Evidence'}}),/lease_rejected/);
 const navigate={op:'navigate',lease_id:broker.frame.lease_id,page:{title:'X',final_url:'https://example.com',text:'Evidence'}};
 await broker.operation(navigate);
 await broker.operation({op:'observe',lease_id:broker.frame.lease_id,instruction:'Identify evidence'});
 const extraction=await broker.operation({op:'extract',lease_id:broker.frame.lease_id,instruction:'Read evidence'});
 assert.equal(extraction.mode,'stagehand_extract_public_snapshot');
 for(const option of options)assert.deepEqual(Object.keys(option as object).sort(),['cache','page','timeout']);
 for(const option of options)assert.equal((option as {cache:boolean}).cache,false);
 const capture=await broker.operation({op:'capture',lease_id:broker.frame.lease_id});assert.equal(capture.bytes,8);
 await broker.operation(navigate);await broker.operation(navigate);
 await assert.rejects(()=>broker.operation(navigate),/page_limit/);
 await broker.operation({op:'close',lease_id:broker.frame.lease_id});await broker.close();
 assert.deepEqual(calls.slice(-3),['page.close','stagehand.close','browser.close']);
 await assert.rejects(()=>broker.operation({op:'capture',lease_id:broker.frame.lease_id}),/lease_rejected/);
});

test('Stagehand actual ClientLLM contract preserves admitted usage and bounds calls',async()=>{
 const initial=frame();let reads=0;
 const iterator={next:async()=>({done:false,value:JSON.stringify({type:'model_result',version:1,lease_id:initial.lease_id,call_id:`${initial.lease_id}_stagehand_${++reads}`,result:{output:{title:'Evidence'},model:'gpt-6.1-sol',effort:'low',usage:{input_tokens:123,output_tokens:45,cost:null}}})})};
 const relay=new BrowserModelRelay(initial,iterator);
 const client=ClientLLMSchema.parse({generate:relay.generate});
 const params={messages:[{role:'user' as const,content:{type:'text' as const,text:'Evidence'}}],responseFormat:{type:'json_schema' as const,name:'evidence',schema:{type:'object',properties:{title:{type:'string'}},required:['title'],additionalProperties:false}}};
 for(let i=0;i<3;i++){
  const result=await client.generate(params);assert.equal(result.outputFormat,'json_schema');assert.deepEqual(result.usage,{inputTokens:123,outputTokens:45,totalTokens:168});
 }
 await assert.rejects(()=>client.generate(params),/model_call_limit/);assert.equal(reads,3);
});

test('Stagehand relay rejects unadmitted AI and image/tool payloads',async()=>{
 const iterator={next:async()=>({done:true as const,value:''})};
 const disabled=new BrowserModelRelay(frame({ai_enabled:false}),iterator);
 await assert.rejects(()=>disabled.generate({messages:[],responseFormat:{type:'json_schema',name:'result',schema:{type:'object'}}}),/model_call_limit/);
 const relay=new BrowserModelRelay(frame(),iterator);
 await assert.rejects(()=>relay.generate({messages:[{role:'user',content:{type:'image',data:'YWJj',mimeType:'image/png'}}],responseFormat:{type:'json_schema',name:'result',schema:{type:'object'}}}),/nontext_browser_input_disabled/);
});

test('pinned Stagehand extension archive exists without any cloud setup',()=>{
 const manifest=extensionManifest();assert.equal(manifest.sdk_version,'4.1.0');assert.equal(manifest.sha256,'8efc7d171a625cca95c02d02d369b59435fae776cae6c7dd2f6fe72eb19785c0');assert.equal(manifest.bytes,440798);
});

test('owned CDP attach inspects pinned installed extension without SDK session lookup or upload',async()=>{
 const initial=frame();const commands:unknown[]=[];let closed=0;let connected:unknown;
 class Socket extends EventTarget {
  constructor(){super();queueMicrotask(()=>this.dispatchEvent(new Event('open')));}
  send(raw:string){commands.push(JSON.parse(raw));queueMicrotask(()=>this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({id:1,result:{extensions:[{id:'a'.repeat(32),name:'Stagehand Runtime',version:'1.0.2',enabled:true}]}})})));}
  close(){closed++;}
 }
 const browser={} as StagehandBrowser;
 const result=await connectOwnedBrowser(initial,{socket:url=>{assert.equal(url,initial.connect_url);return new Socket() as unknown as WebSocket;},connect:async(options)=>{connected=options;return browser;}});
 assert.equal(result,browser);assert.equal(closed,1);
 assert.deepEqual(commands,[{id:1,method:'Extensions.getExtensions',params:{}}]);
 assert.deepEqual(connected,{cdpUrl:initial.connect_url,extensionId:'a'.repeat(32)});
});

test('disconnect-sensitive owned cloud session stays connected during extension-to-SDK handoff',async()=>{
 let connections=0;let terminal=false;let probeCloses=0;
 class Socket extends EventTarget {
  constructor(){super();connections++;queueMicrotask(()=>this.dispatchEvent(new Event('open')));}
  send(){queueMicrotask(()=>this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({id:1,result:{extensions:[{id:'a'.repeat(32),name:'Stagehand Runtime',version:'1.0.2',enabled:true}]}})})));}
  close(){probeCloses++;if(--connections===0)terminal=true;}
 }
 const browser={close:async()=>{if(--connections===0)terminal=true;}} as StagehandBrowser;
 const result=await connectOwnedBrowser(frame(),{socket:()=>new Socket() as unknown as WebSocket,connect:async()=>{
  // Browserbase keepAlive=false ends a session when its final connection closes.
  assert.equal(terminal,false,'Inspection must remain attached until SDK attachment succeeds');
  assert.equal(connections,1);connections++;return browser;
 }});
 assert.equal(result,browser);assert.equal(probeCloses,1);assert.equal(connections,1);assert.equal(terminal,false);
 await result.close();assert.equal(connections,0);assert.equal(terminal,true);
});

test('failed SDK handoff closes the retained probe once and emits no provider exception text',async()=>{
 let closed=0;
 class Socket extends EventTarget {
  constructor(){super();queueMicrotask(()=>this.dispatchEvent(new Event('open')));}
  send(){queueMicrotask(()=>this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({id:1,result:{extensions:[{id:'a'.repeat(32),name:'Stagehand Runtime',version:'1.0.2',enabled:true}]}})})));}
  close(){closed++;}
 }
 await assert.rejects(()=>connectOwnedBrowser(frame(),{socket:()=>new Socket() as unknown as WebSocket,connect:async()=>{
  assert.equal(closed,0);throw new Error('private signed URL/apiKey=secret');
 }}),error=>error instanceof Error&&error.message==='browser_transport_failed');
 assert.equal(closed,1);
});

test('fixed phase diagnostics retain specific timeout codes without retaining raw errors',async()=>{
 for(const phase of ['stagehand_initialization_failed','browser_snapshot_render_failed','browser_snapshot_capture_failed','stagehand_observation_failed','stagehand_extraction_failed','browser_cleanup_failed'] as const){
  await assert.rejects(()=>withBrowserPhase(phase,async()=>{throw new Error('private signed URL/apiKey=secret');}),error=>error instanceof Error&&classifyBrowserFailure(error)===phase);
  await assert.rejects(()=>withBrowserPhase(phase,async()=>{throw new Error('Stagehand operation timed out at private URL');}),error=>error instanceof Error&&classifyBrowserFailure(error)==='stagehand_operation_timeout');
 }
});

test('missing/ambiguous installed extension is closed and fixed failure codes do not leak details',async()=>{
 let closed=0;let connected=false;
 class Socket extends EventTarget {
  constructor(){super();queueMicrotask(()=>this.dispatchEvent(new Event('open')));}
  send(){queueMicrotask(()=>this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({id:1,result:{extensions:[]}})})));}
  close(){closed++;}
 }
 await assert.rejects(()=>connectOwnedBrowser(frame(),{socket:()=>new Socket() as unknown as WebSocket,connect:async()=>{connected=true;return {} as StagehandBrowser;}}),/stagehand_extension_unavailable/);
 assert.equal(closed,1);assert.equal(connected,false);
 assert.equal(classifyBrowserFailure(new Error('private URL/apiKey=secret')),'browser_operation_failed');
 assert.equal(classifyBrowserFailure(new Error('stagehand_extension_inspection_failed')),'stagehand_extension_inspection_failed');
 assert.equal(classifyBrowserFailure(new Error('Stagehand initialization timed out after 60000ms')),'stagehand_operation_timeout');
});
