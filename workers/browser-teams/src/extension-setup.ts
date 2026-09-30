// Operator-only setup: upload the exact pinned SDK extension, never create a session.
import Browserbase from '@browserbasehq/sdk';
import {createReadStream,readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import { emit } from './protocol.js';

export function extensionManifest(){
 const path=fileURLToPath(new URL('../../node_modules/@browserbasehq/stagehand/dist/assets/stagehand-extension.zip',import.meta.url));
 const bytes=readFileSync(path);
 return {path,sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,sdk_version:'4.1.0'};
}
async function main(){
 const artifact=extensionManifest();
 if(process.argv.includes('--inspect')){const {path:_,...metadata}=artifact;emit({version:1,...metadata});return;}
 if(!process.env.BROWSERBASE_API_KEY)throw new Error('browser_key_missing');
 const client=new Browserbase({apiKey:process.env.BROWSERBASE_API_KEY,maxRetries:0,timeout:20000});
 const extension=await client.extensions.create({file:createReadStream(artifact.path)});
 if(!/^[a-f0-9-]{36}$/i.test(extension.id))throw new Error('invalid_extension_receipt');
 const confirmed=await client.extensions.retrieve(extension.id);
 if(confirmed.id!==extension.id||!confirmed.projectId||confirmed.projectId!==extension.projectId||confirmed.fileName!==extension.fileName)throw new Error('extension_readback_failed');
 const {path:_,...metadata}=artifact;
 emit({version:1,extension_id:extension.id,project_id:confirmed.projectId,file_name:confirmed.fileName,readback_confirmed:true,...metadata});
}
if(process.argv[1]?.endsWith('extension-setup.js'))main().catch(()=>{emit({type:'error',version:1,code:'extension_setup_failed'});process.exitCode=1;});
