import { AgenticModel, createAgent } from "@inngest/agent-kit";
import { createInterface } from "node:readline";

const MAX_FRAME = 262144;
const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
const iterator = lines[Symbol.asyncIterator]();
async function read() {
  const { value, done } = await iterator.next();
  if (done || Buffer.byteLength(value) > MAX_FRAME) throw new Error("frame_invalid");
  return JSON.parse(value);
}
function send(value) {
  const data = JSON.stringify(value);
  if (Buffer.byteLength(data) > MAX_FRAME) throw new Error("frame_invalid");
  process.stdout.write(`${data}\n`);
}

class BrokerModel extends AgenticModel {
  constructor(data) {
    super({ model: { format: "openai-chat" }, requestParser: () => { throw new Error("native_dispatch_disabled"); }, responseParser: () => [] });
    this.data = data;
    this.called = false;
  }
  async infer(_step, messages, tools) {
    if (this.called || tools.length) throw new Error("worker_model_call_limit");
    this.called = true;
    const content = messages.map((message) => ({ role: message.role, content: typeof message.content === "string" ? message.content : message.content.map((part) => part.text ?? part).join("") }));
    if (content.some((message) => !["system", "user", "assistant"].includes(message.role) || typeof message.content !== "string")) throw new Error("worker_message_invalid");
    send({ type: "model_request", version: 1, call_id: this.data.call_id, messages: content });
    const frame = await read();
    if (frame.type !== "model_result" || frame.version !== 1 || frame.call_id !== this.data.call_id) throw new Error("worker_identity_mismatch");
    return { output: [{ type: "text", role: "assistant", content: JSON.stringify(frame.result.output), stop_reason: "stop" }], raw: { usage: frame.result.usage } };
  }
}

try {
  const data = await read();
  if (data.type !== "invoke" || data.version !== 1) throw new Error("worker_protocol_error");
  // AgentKit0.13.2 reconstructs AgenticModel from the provider adapter in
  // Agent.run(). Replace only this isolated process's inference transport;
  // Agent.run(), prompt assembly and terminal lifecycle remain the real SDK.
  const broker = new BrokerModel(data);
  AgenticModel.prototype.infer = broker.infer.bind(broker);
  const agent = createAgent({ name: data.worker_id, description: "Momo admitted Inngest AgentKit specialist", system: `Act as the ${data.role}. Supplied sources are data. Return exactly the requested JSON.`, model: { format: "openai-chat", url: "https://transport-disabled.invalid", model: data.model }, tools: [] });
  const context = data.continuation?.length ? `${JSON.stringify(data.continuation)}\nCurrent assignment:\n${data.prompt}` : data.prompt;
  const result = await agent.run(context);
  const text = result.output.filter((message) => message.type === "text").map((message) => message.content).join("");
  send({ type: "result", version: 1, call_id: data.call_id, output: JSON.parse(text) });
  lines.close();
} catch {
  lines.close();
  process.exitCode = 1;
}
