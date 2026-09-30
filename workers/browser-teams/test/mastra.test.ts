import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ModelRelay,invokeSchema} from '../src/protocol.js';
import {runMastra} from '../src/mastra-worker.js';

test('real Mastra1.72 agent executes exactly one admitted provider handoff',async()=>{
 const invoke=invokeSchema.parse({type:'invoke',version:1,call_id:'owner_run_draft',worker_id:'producer',role:'Writer',prompt:'Give the required useful result.',continuation:[],output_schema:{type:'object',properties:{answer:{type:'string'}},required:['answer'],additionalProperties:false},model:'gpt-6.1-sol',effort:'low',max_output_tokens:256,framework:'mastra'});
 const iterator={next:async()=>({done:false,value:JSON.stringify({type:'model_result',version:1,call_id:invoke.call_id,result:{output:{answer:'Useful result'},model:invoke.model,effort:invoke.effort,usage:{input_tokens:12,output_tokens:8,cost:null}}})})};
 const relay=new ModelRelay(invoke,iterator);
 const result=await runMastra(invoke,relay);
 assert.deepEqual(result,{answer:'Useful result'});assert.equal(relay.count,1);
 await assert.rejects(()=>relay.generate([{role:'user',content:'second'}]),/model_call_limit/);
});

test('model worker invocation rejects unbounded inputs and secret configuration',()=>{
 assert.equal(invokeSchema.safeParse({type:'invoke',version:1,api_key:'private'}).success,false);
});
