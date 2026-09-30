import { Agent } from '@mastra/core/agent';
import type { LanguageModelV2, LanguageModelV2CallOptions, LanguageModelV2StreamPart } from '@ai-sdk/provider';
import { emit,invokeSchema,lines,receive,ModelRelay,type Message,type Invocation } from './protocol.js';

export async function runMastra(invocation:Invocation, relay:ModelRelay):Promise<Record<string,unknown>>{
  const generate=async(options:LanguageModelV2CallOptions)=>{
    const messages:Message[]=options.prompt.map(message=>{
      if(!['user','assistant','system'].includes(message.role))throw new Error('unsupported_role');
      const content=typeof message.content==='string'?message.content:message.content.map(part=>{if(part.type!=='text'||typeof part.text!=='string')throw new Error('unsupported_content');return part.text;}).join('\n');
      return {role:message.role as Message['role'],content};
    });
    const result=await relay.generate(messages);
    return {content:[{type:'text' as const,text:JSON.stringify(result.output)}],finishReason:'stop' as const,usage:{inputTokens:result.usage.input_tokens,outputTokens:result.usage.output_tokens,totalTokens:result.usage.input_tokens+result.usage.output_tokens},warnings:[]};
  };
  // Standard AI SDK v2 custom provider; Mastra1.72 supports v2/v3/v4.
  const model:LanguageModelV2={specificationVersion:'v2' as const,provider:'momobot-admitted-responses',modelId:invocation.model,supportedUrls:{},doGenerate:generate,doStream:async(options)=>{const result=await generate(options);return {stream:new ReadableStream<LanguageModelV2StreamPart>({start(controller){controller.enqueue({type:'stream-start',warnings:[]});controller.enqueue({type:'text-start',id:'answer'});controller.enqueue({type:'text-delta',id:'answer',delta:result.content[0]!.text});controller.enqueue({type:'text-end',id:'answer'});controller.enqueue({type:'finish',finishReason:'stop',usage:result.usage});controller.close();}})};}};
  const agent=new Agent({id:invocation.worker_id,name:invocation.role,instructions:'Complete the scoped server-owned task. Return only its requested JSON object. No tools, delegation or external actions are authorized.',model,tools:{},maxRetries:0,maxProcessorRetries:0});
  const output=await agent.generate([...invocation.continuation.map(message=>message.role==='user'?{role:'user' as const,content:message.content}:{role:'assistant' as const,content:message.content}),{role:'user' as const,content:invocation.prompt}],{maxSteps:1,modelSettings:{maxOutputTokens:invocation.max_output_tokens},abortSignal:AbortSignal.timeout(65000)});
  if(relay.count!==1 || !relay.result)throw new Error('missing_handoff');
  const value=JSON.parse(output.text);
  if(JSON.stringify(value)!==JSON.stringify(relay.result.output))throw new Error('output_mismatch');
  return value;
}

async function main(){
  if(Object.keys(process.env).some(name=>name.endsWith('API_KEY')))throw new Error('credential_environment_rejected');
  const iterator=lines();const invocation=invokeSchema.parse(await receive(iterator));
  const relay=new ModelRelay(invocation,iterator);
  const output=await runMastra(invocation,relay);
  emit({type:'result',version:1,call_id:invocation.call_id,output});
}
if(process.argv[1]?.endsWith('mastra-worker.js')){
  // Third-party logs go only to discarded stderr; protocol stdout is exclusive.
  console.log=()=>{};console.info=()=>{};console.warn=()=>{};console.error=()=>{};
  main().then(()=>process.exit(0)).catch(()=>{emit({type:'error',version:1,code:'isolated_worker_failed'});process.exit(1);});
}
