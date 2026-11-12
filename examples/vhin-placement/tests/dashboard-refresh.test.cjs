const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function dashboard() {
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, {innerHTML:"", textContent:"", addEventListener(){}});
    return nodes.get(id);
  };
  const requests = [];
  const context = vm.createContext({
    document:{getElementById:node, querySelectorAll:()=>[], addEventListener(){}},
    URLSearchParams, Intl, Date,
    fetch:()=>new Promise((resolve, reject)=>requests.push({resolve, reject})),
  });
  const source = fs.readFileSync(path.join(__dirname,"../vhin_placement/static/app.js"),"utf8");
  assert.ok(source.endsWith("action(async () => {});\n"));
  vm.runInContext(source.slice(0,source.lastIndexOf("action(async () => {});")),context);
  vm.runInContext("render = () => {}; formData = () => ({city:'Tampa'});",context);
  const answer = (request, data) => request.resolve({ok:true,json:async()=>data});
  return {node, requests, context, answer};
}

test("record refresh removes old recommendation claims before its request completes", async()=>{
  const d = dashboard();
  d.node("recommend-results").innerHTML = "Old human-confirmed openings";
  const refreshing = vm.runInContext("refresh()",d.context);
  assert.doesNotMatch(d.node("recommend-results").innerHTML,/Old human-confirmed/);
  d.answer(d.requests[0],{});
  await refreshing;
  assert.match(d.node("recommend-results").innerHTML,/Run Top 3 again/);
});

test("failed refresh still removes stale recommendations", async()=>{
  const d = dashboard();
  d.node("recommend-results").innerHTML = "Old ranking";
  const refreshing = vm.runInContext("refresh()",d.context);
  d.requests[0].reject(new Error("offline"));
  await assert.rejects(refreshing,/offline/);
  assert.doesNotMatch(d.node("recommend-results").innerHTML,/Old ranking/);
});

test("a recommendation response started before refresh cannot restore stale results", async()=>{
  const d = dashboard();
  const lookup = vm.runInContext("lookup({id:'recommend-form'})",d.context);
  const refreshing = vm.runInContext("refresh()",d.context);
  d.answer(d.requests[1],{});
  await refreshing;
  d.answer(d.requests[0],{recommendations:[]});
  await lookup;
  assert.match(d.node("recommend-results").innerHTML,/Run Top 3 again/);
});
