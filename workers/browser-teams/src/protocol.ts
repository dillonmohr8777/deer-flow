import { createInterface } from 'node:readline';
import { z } from 'zod';

export const MAX_FRAME = 262144;
const identity = z.string().regex(/^[A-Za-z0-9_-]{1,128}$/);
export const invokeSchema = z.object({type:z.literal('invoke'),version:z.literal(1),call_id:identity,worker_id:identity,role:z.string().min(1).max(200),prompt:z.string().min(1).max(131072),continuation:z.array(z.object({role:z.enum(['user','assistant']),content:z.string().max(48000)}).strict()).max(4),output_schema:z.record(z.string(),z.unknown()),model:z.literal('gpt-6.1-sol'),effort:z.enum(['low','medium','high']),max_output_tokens:z.number().int().min(32).max(8192),input_token_limit:z.number().int().min(0).max(60000).default(60000),framework:z.string()}).strict();
export type Invocation = z.infer<typeof invokeSchema>;
export type Message = {role:'system'|'user'|'assistant';content:string};
export type ModelResult = {output:Record<string,unknown>;model:string;effort:string;usage:{input_tokens:number;output_tokens:number;cost:number|null}};

export function emit(frame:unknown, limit=MAX_FRAME):void {
  const line=JSON.stringify(frame);
  if(Buffer.byteLength(line)>limit)throw new Error('frame_too_large');
  process.stdout.write(line+'\n');
}

export function lines():AsyncIterator<string> {
  // Prevent readline from accumulating an unbounded malicious unterminated frame.
  let pending=0;
  process.stdin.on('data',(chunk:Buffer)=>{
    for(const byte of chunk){if(byte===10)pending=0;else if(++pending>MAX_FRAME){process.exit(2);}}
  });
  return createInterface({input:process.stdin,crlfDelay:Infinity})[Symbol.asyncIterator]();
}
export async function receive(iterator:AsyncIterator<string>):Promise<unknown>{
  const row=await iterator.next();
  if(row.done || Buffer.byteLength(row.value)>MAX_FRAME)throw new Error('invalid_frame');
  return JSON.parse(row.value);
}
export class ModelRelay {
  count=0;
  result:ModelResult|undefined;
  constructor(readonly invocation:Invocation, readonly iterator:AsyncIterator<string>){}
  async generate(messages:Message[]):Promise<ModelResult>{
    if(++this.count!==1)throw new Error('model_call_limit');
    emit({type:'model_request',version:1,call_id:this.invocation.call_id,messages});
    const reply=z.object({type:z.literal('model_result'),version:z.literal(1),call_id:z.literal(this.invocation.call_id),result:z.object({output:z.record(z.string(),z.unknown()),model:z.literal(this.invocation.model),effort:z.literal(this.invocation.effort),usage:z.object({input_tokens:z.number().int().nonnegative(),output_tokens:z.number().int().nonnegative(),cost:z.number().nonnegative().nullable()})}).passthrough()}).strict().parse(await receive(this.iterator));
    this.result=reply.result;
    return reply.result;
  }
}
