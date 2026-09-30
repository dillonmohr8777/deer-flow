// Opt-in disposable headless Chrome, no cloud/model providers and no live user browser.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {z} from 'zod';
import {localBrowser,Stagehand, type ClientLLM} from '@browserbasehq/stagehand';
import {createServer} from 'node:net';
import {setTimeout as delay} from 'node:timers/promises';
import {SnapshotBrowserBroker,connectOwnedBrowser, type OpenFrame} from '../src/browser-worker.js';

test('real Stagehand4 extension extracts a disposable inert snapshot through custom LLM',{skip:process.env.MOMOBOT_RUN_HEADLESS_STAGEHAND_SMOKE!=='1',timeout:90000},async()=>{
 const browser=await localBrowser.launch({headless:true,acceptDownloads:false});
 let calls=0;let sourceObserved=false;
 const model:ClientLLM={generate:async(params)=>{
  calls++;
  sourceObserved ||= JSON.stringify(params.messages).includes('Offline source evidence');
  assert.equal(params.responseFormat?.type,'json_schema');
  const isProgress=JSON.stringify(params.responseFormat?.schema).includes('\"completed\"');
  const output=isProgress?{progress:'Visible evidence extracted',completed:true}:{title:'Offline source',summary:'Offline source evidence',claims:[{claim:'Evidence is present',quote:'Offline source evidence'}]};
  return {role:'assistant',content:{type:'text',text:JSON.stringify(output)},outputFormat:'json_schema',structuredContent:z.json().parse(output),usage:{inputTokens:12,outputTokens:8,totalTokens:20}};
 }};
 let stagehand:Stagehand|undefined;
 try{
  stagehand=await Stagehand.create({browser,model,cache:false,logging:{level:'off'}});
  const frame={type:'open',version:1,lease_id:'offline_owner_lease',deadline_ms:Date.now()+60000,connect_url:'offline',session_id:'12345678-1234-4234-8234-123456789abc',api_key:'not-used',ai_enabled:true} as OpenFrame;
  const broker=new SnapshotBrowserBroker(frame,stagehand,browser);
  await broker.operation({op:'navigate',lease_id:frame.lease_id,page:{title:'Offline source',final_url:'https://example.com',text:'Offline source evidence'}});
  const extract=await broker.operation({op:'extract',lease_id:frame.lease_id,instruction:'Read visible evidence and source title'});
  assert.equal(calls,2);assert.equal(sourceObserved,true);assert.equal((extract.data as {summary:string}).summary,'Offline source evidence');
  const capture=await broker.operation({op:'capture',lease_id:frame.lease_id});assert.ok((capture.bytes as number)>1000);
  await broker.close();
 }finally{try{await stagehand?.close();}finally{await browser.close();}}
});

test('real existing-browser CDP transport finds pinned extension, captures, and closes only its owned browser',{skip:process.env.MOMOBOT_RUN_HEADLESS_STAGEHAND_SMOKE!=='1',timeout:90000},async()=>{
 const reservation=createServer();await new Promise<void>(resolve=>reservation.listen(0,'127.0.0.1',resolve));
 const address=reservation.address();assert.ok(address&&typeof address==='object');const port=address.port;
 await new Promise<void>((resolve,reject)=>reservation.close(error=>error?reject(error):resolve()));
 const owner=await localBrowser.launch({headless:true,port,acceptDownloads:false});
 let attached:Awaited<ReturnType<typeof connectOwnedBrowser>>|undefined;
 let attachedStagehand:Stagehand|undefined;
 const model:ClientLLM={generate:async()=>{throw new Error('Offline transport must not invoke a model');}};
 try{
  const response=await fetch(`http://127.0.0.1:${port}/json/version`);assert.equal(response.status,200);
  const metadata=await response.json() as {webSocketDebuggerUrl:string};
  assert.ok(metadata.webSocketDebuggerUrl.startsWith(`ws://127.0.0.1:${port}/`));
  const frame={type:'open',version:1,lease_id:'offline_cdp_lease',deadline_ms:Date.now()+60000,connect_url:metadata.webSocketDebuggerUrl,session_id:'12345678-1234-4234-8234-123456789abc',api_key:'not-used',ai_enabled:false} as OpenFrame;
  attached=await connectOwnedBrowser(frame);
  attachedStagehand=await Stagehand.create({browser:attached,model,cache:false,logging:{level:'off'}});
  const page=await attached.context.newPage('data:text/html,<p>Owned offline transport</p>');
  assert.ok((await page.screenshot({type:'png',fullPage:false})).length>1000);await page.close();
  await attachedStagehand.close();await attached.close();assert.equal(attached.closed,true);
  // Pinned localBrowser.connect.close sends Browser.close. This test owns the
  // disposable Chrome; production owns only the protected remote session.
  let ownerStopped=false;const shutdownDeadline=Date.now()+5000;
  while(Date.now()<shutdownDeadline){
   try{await fetch(`http://127.0.0.1:${port}/json/version`,{signal:AbortSignal.timeout(1000)});}catch{ownerStopped=true;break;}
   await delay(100);
  }
  assert.equal(ownerStopped,true,'Owned Chrome must terminate after SDK Browser.close');
 }finally{try{await attachedStagehand?.close();await attached?.close();}finally{await owner.close();}}
});
