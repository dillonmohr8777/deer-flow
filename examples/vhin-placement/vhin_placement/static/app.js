"use strict";
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = (cents) => new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(cents / 100);
const fact = (label, value) => `<div class="fact"><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value || "Not recorded")}</dd></div>`;
const humanLabel = (text) => String(text).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
const localTime = (value) => value ? new Date(value).toLocaleString("en-US",{timeZone:"America/New_York",dateStyle:"medium",timeStyle:"short"}) + " ET" : "Not recorded";
let state, selected, busy = false;
const pendingWrites = new Map();

async function api(path, body, method = "POST") {
  const options = {method:body === undefined ? "GET" : method, credentials:"same-origin", headers:{}};
  if (body !== undefined) {
    const csrfCookie = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrf_token="));
    if (!csrfCookie) throw new Error("Refresh your MomoBot sign-in before saving changes.");
    options.body = JSON.stringify(body);
    const signature = `${method}:${path}:${options.body}`;
    if (!pendingWrites.has(signature)) pendingWrites.set(signature, crypto.randomUUID());
    options.headers = {"Content-Type":"application/json", "Idempotency-Key":pendingWrites.get(signature), "X-CSRF-Token":decodeURIComponent(csrfCookie.slice("csrf_token=".length))};
  }
  const response = await fetch(`/api/vhin${path}`, options);
  let data;
  try { data = await response.json(); } catch { throw new Error(`Workspace request failed (${response.status}). Refresh your MomoBot session.`); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  if (body !== undefined) pendingWrites.delete(`${method}:${path}:${options.body}`);
  return data;
}
function failure(error) { $("failure").hidden = false; $("failure").textContent = error.message; $("notice").textContent = "Action needs attention. Your last saved records are still shown."; }
function view(name) {
  document.querySelectorAll(".view").forEach((node) => { node.hidden = node.id !== name; });
  document.querySelectorAll("[data-view]").forEach((node) => { node.toggleAttribute("aria-current", node.dataset.view === name); if (node.hasAttribute("aria-current")) node.setAttribute("aria-current", "page"); });
}
async function refresh() {
  state = await api("/state");
  render();
  $("notice").textContent = `Records read from your workspace at ${localTime(new Date().toISOString())}.`;
}
async function action(operation) {
  if (busy) return;
  busy = true;
  $("failure").hidden = true;
  document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try { await operation(); await refresh(); }
  catch (error) { failure(error); }
  finally { busy = false; document.querySelectorAll("button").forEach((button) => { button.disabled = false; }); }
}
function formData(form) { return Object.fromEntries(new FormData(form)); }
function compact(data) { return Object.fromEntries(Object.entries(data).filter(([,value]) => value !== "")); }
function render() {
  const referrals = state.referrals || [], totals = state.briefing?.totals || state.briefing || {};
  $("count").textContent = referrals.filter((r) => r.status !== "Placed").length;
  for (const field of ["contracted", "invoiced", "collected"]) {
    const amount = totals[`${field}_cents`];
    $(field).textContent = Number.isInteger(amount) ? money(amount) : "Not recorded";
  }
  const attention = referrals.filter((r) => r.missing_info?.length || r.attention === "urgent" || r.attention === "human_request");
  $("briefing-content").innerHTML = `<h3>Family review</h3>${attention.map((r) => `<div class="activity"><strong>${escapeHTML(r.name)}</strong><p>${r.attention && r.attention !== "routine" ? `${escapeHTML(humanLabel(r.attention))}. ` : ""}${escapeHTML((r.missing_info || []).map(humanLabel).join(", ") || "Human callback needed")}</p><button class="secondary" data-open-case="${escapeHTML(r.id)}">Review family</button></div>`).join("") || '<p>No intake gaps recorded.</p>'}<div class="action-group"><h3>Tours and collections</h3><p>${Number(totals.proposed_tours || 0)} proposed tours · ${Number(totals.confirmed_tours || 0)} confirmed tours</p><p>Due now: <strong>${Number.isInteger(totals.due_cents) ? money(totals.due_cents) : "Not recorded"}</strong></p><p>${Number(totals.availability_needs_verification || 0)} communities need availability verification.</p></div>`;
  $("audit").innerHTML = (state.audit || []).slice(0,12).map((event) => `<div class="activity"><strong>${escapeHTML(humanLabel(event.action.replaceAll(".", " ").split(":")[0]))}</strong><br><small>${escapeHTML(localTime(event.at || event.created_at))}</small></div>`).join("") || "No activity recorded yet.";
  $("case-list").innerHTML = referrals.map((r) => `<button class="case-row" data-case="${escapeHTML(r.id)}" aria-pressed="${r.id === selected}"><strong>${escapeHTML(r.name)}</strong><small>${escapeHTML(r.status)} · ${escapeHTML(r.location || "Area not recorded")}</small><br><span class="badge">${escapeHTML(r.contact_status || "active")}</span></button>`).join("") || '<p class="muted">No referrals yet. Save the first record from Grace\'s intake.</p>';
  $("community-list").innerHTML = (state.communities || []).map((c) => `<article class="panel"><h3>${escapeHTML(c.name)}</h3><p>${escapeHTML(c.city)} · ${escapeHTML(c.licensed_beds ?? "Unknown")} licensed capacity</p><dl>${fact("Source",c.source_url)}${fact("Observed",localTime(c.observed_at))}${fact("Openings",c.availability?.status === "verified" ? `${c.availability.vacancies} human-confirmed, expires ${localTime(c.availability.expires_at)}` : "Unknown; human verification needed")}</dl><form data-availability="${escapeHTML(c.id)}"><label>Human-confirmed openings<input name="vacancies" type="number" min="0" step="1" required></label><label>Verified at (your device timezone)<input name="verified_at" type="datetime-local" required></label><label>Expires at (your device timezone)<input name="expires_at" type="datetime-local" required></label><label>Verification reference<input name="source_ref" required placeholder="Conversation or source reference"></label><button>Record verification</button></form></article>`).join("") || '<p class="muted">No sourced community records yet. Licensed capacity does not establish openings.</p>';
  const connectionNames = {intake:"Referral intake",calendar:"Calendar booking",sender:"Email and text delivery",billing:"Billing provider"};
  $("connection-list").innerHTML = Object.entries(state.connections || {}).map(([key,value]) => `<div class="activity"><h3>${escapeHTML(connectionNames[key] || humanLabel(key))}</h3><p>${value === "manual" ? "Manual entry is ready. Grace's form connection is still needed." : value === "unconnected" ? "Account connection and an accepted test are still needed." : escapeHTML(humanLabel(value))}</p></div>`).join("");
  if (selected) renderCase();
}
function renderCase() {
  const r = state.referrals.find((row) => row.id === selected);
  if (!r) { selected = null; $("case-detail").hidden = true; return; }
  $("intake").hidden = true; $("case-detail").hidden = false;
  const communities = (state.communities || []).map((c) => `<option value="${escapeHTML(c.id)}">${escapeHTML(c.name)}</option>`).join("");
  const placement = (state.placements || []).find((p) => p.referral_id === r.id);
  const fields = [["name","Name",r.name],["responsible_contact","Responsible contact",r.responsible_contact],["phone","Phone",r.phone],["email","Email",r.email],["location","Area",r.location],["care_needs","Assistance needs",r.care_needs],["timing","Move timing",r.timing]];
  $("case-detail").innerHTML = `<div class="section-title"><h2>${escapeHTML(r.name)}</h2><span>${escapeHTML(r.status)}</span></div><p class="muted">Case ${escapeHTML(r.id)}</p><dl>${fact("Missing information",(r.missing_info || []).join(", ") || "No required gaps")}${fact("Contact status",r.contact_status)}${fact("Human attention",humanLabel(r.attention || "routine"))}</dl>
    <details class="action-group"><summary>Review and update intake</summary><form id="edit-referral"><div class="two">${fields.map(([name,label,value]) => `<label>${label}<input name="${name}" value="${escapeHTML(value)}" ${name === "name" ? "required" : ""}></label>`).join("")}<label>Monthly budget ($)<input name="budget" type="number" min="0" step="0.01" value="${r.budget_cents == null ? "" : r.budget_cents / 100}"></label><label>Contact preference<select name="contact_preference">${["none","phone","email"].map((v) => `<option value="${v}" ${v === r.contact_preference ? "selected" : ""}>${v === "none" ? "Not confirmed" : v}</option>`).join("")}</select></label></div><button>Save changes</button></form></details>
    <div class="action-group"><h3>Workflow review</h3><div class="actions">${r.status === "New" ? '<button data-transition="Qualified">Mark qualified after review</button>' : ""}${r.status === "Qualified" ? '<button data-transition="Touring">Move to touring</button>' : ""}<button class="secondary" data-contact="reply">Record family reply</button><button class="secondary" data-contact="stop">Record stop request</button></div></div>
    <div class="action-group"><h3>Family follow-up</h3><form id="draft-form"><label>Reason<select name="reason"><option value="incomplete">Incomplete intake</option><option value="no_booking">No tour yet</option><option value="missed_tour">Missed tour</option><option value="completed_tour">Tour completed</option><option value="planning">Planning ahead</option></select></label><label>Message for review<textarea name="body" rows="3" required></textarea></label><button>Save draft</button></form><div>${(r.drafts || state.drafts?.filter((d) => d.referral_id === r.id) || []).map((d) => `<div class="activity"><span class="badge">${escapeHTML(d.status)}</span><p>${escapeHTML(d.body)}</p></div>`).join("")}</div></div>
    <div class="action-group"><h3>Community comparison</h3><p class="muted">Review sourced facts with Justin. Openings and care fit require human confirmation.</p>${[...(state.communities || [])].sort((a,b) => Number(b.city.toLowerCase() === (r.location || "").toLowerCase()) - Number(a.city.toLowerCase() === (r.location || "").toLowerCase())).map((c) => `<div class="activity"><h3>${escapeHTML(c.name)}</h3><p>${escapeHTML(c.city)} · ${escapeHTML((c.services || []).join(", ") || "Services need verification")}</p><p>${c.availability?.status === "verified" ? `${c.availability.vacancies} human-confirmed openings` : "Availability unknown"}</p><small>Source: ${escapeHTML(c.source_url)} · ${escapeHTML(localTime(c.observed_at))}</small></div>`).join("") || '<p>Add a sourced community to compare it with this family.</p>'}</div>
    <div class="action-group"><h3>Tour proposal</h3><form id="tour-form"><label>Community<select name="community_id" required><option value="">Choose a community</option>${communities}</select></label><div class="two"><label>Start (your device timezone)<input name="start_at" type="datetime-local" required></label><label>End (your device timezone)<input name="end_at" type="datetime-local" required></label></div><button>Save proposed tour</button></form><div>${(state.tours || []).filter((t) => t.referral_id === r.id).map((t) => `<p>${escapeHTML(localTime(t.start_at))} · ${escapeHTML(t.status)}</p>`).join("")}</div></div>
    <div class="action-group"><h3>Placement and fee milestones</h3>${placement ? `<dl>${fact("Contracted fee",money(placement.fee_cents))}${fact("Move-in",placement.move_in_date)}${fact("Signed agreement",placement.agreement_ref)}</dl>${placement.installments.map((i) => `<p>Day ${i.day}: <strong>${money(i.amount_cents)}</strong> due ${escapeHTML(i.due_date)}</p>`).join("")}<form id="ledger-form" data-placement="${escapeHTML(placement.id)}"><div class="two"><label>Record type<select name="kind"><option value="invoiced">Invoice issued</option><option value="collected">Payment received</option></select></label><label>Installment<select name="day"><option value="30">Day 30</option><option value="60">Day 60</option></select></label><label>Amount ($)<input name="amount" type="number" min="0.01" step="0.01" required></label><label>Event date<input name="event_date" type="date" required></label></div><label>Receipt reference<input name="receipt_ref" required></label><button>Record financial evidence</button></form>` : `<p class="muted">Only the configured placement confirmer can record move-in and signed terms.</p><form id="placement-form"><label>Community<select name="community_id" required><option value="">Choose a community</option>${communities}</select></label><div class="two"><label>Move-in date<input name="move_in_date" type="date" required></label><label>Agreement signed on<input name="agreement_signed_on" type="date" required></label><label>Total fee ($)<input name="fee" type="number" min="0.01" step="0.01" required></label><label>Signed agreement reference<input name="agreement_ref" required></label></div><label>Agreed refund / proration terms<textarea name="refund_terms" required></textarea></label><button>Confirm move-in and signed terms</button></form>`}</div>`;
}
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => view(button.dataset.view)));
$("refresh").addEventListener("click", () => action(async () => {}));
$("new-case").addEventListener("click", () => { selected = null; $("case-detail").hidden = true; $("intake").hidden = false; });
$("case-list").addEventListener("click", (event) => { const button = event.target.closest("[data-case]"); if (button) { selected = button.dataset.case; render(); } });
document.addEventListener("click", (event) => {
  const openCase = event.target.closest("[data-open-case]");
  if (openCase) { selected = openCase.dataset.openCase; render(); view("cases"); return; }
  const button = event.target.closest("[data-transition], [data-contact]");
  if (!button) return;
  action(async () => {
    if (button.dataset.transition) await api(`/referrals/${selected}/transition`,{status:button.dataset.transition,human_confirmed:true});
    else await api(`/referrals/${selected}/contact-events`,{event:button.dataset.contact});
  });
});
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  event.preventDefault();
  action(async () => {
    let data = formData(form);
    if (form.id === "referral-form") {
      data.budget_cents = data.budget === "" ? null : Math.round(Number(data.budget) * 100); delete data.budget;
      const saved = await api("/referrals",compact(data)); selected = saved.id || saved.referral?.id; form.reset();
    } else if (form.id === "edit-referral") {
      data.budget_cents = data.budget === "" ? null : Math.round(Number(data.budget) * 100); delete data.budget;
      data = Object.fromEntries(Object.entries(data).map(([key,value]) => [key,value === "" ? null : value]));
      data.expected_version = state.referrals.find((r) => r.id === selected).version;
      await api(`/referrals/${selected}`,data,"PATCH");
    } else if (form.id === "community-form") {
      data.services = data.services.split(",").map((s) => s.trim()).filter(Boolean);
      data.licensed_beds = data.licensed_beds === "" ? null : Number(data.licensed_beds);
      data.observed_at = new Date(data.observed_at).toISOString();
      await api("/communities",data); form.reset();
    } else if (form.dataset.availability) {
      data.vacancies = Number(data.vacancies); data.human_confirmed = true;
      data.verified_at = new Date(data.verified_at).toISOString(); data.expires_at = new Date(data.expires_at).toISOString();
      await api(`/communities/${form.dataset.availability}/availability`,data);
    } else if (form.id === "draft-form") await api(`/referrals/${selected}/drafts`,data);
    else if (form.id === "tour-form") {
      data.referral_id = selected;
      data.start_at = new Date(data.start_at).toISOString(); data.end_at = new Date(data.end_at).toISOString();
      await api("/tours",data);
    } else if (form.id === "placement-form") {
      data.referral_id = selected; data.terms = "50_50_day30_day60"; data.fee_cents = Math.round(Number(data.fee) * 100); delete data.fee;
      await api("/placements",data);
    } else if (form.id === "ledger-form") {
      data.day = Number(data.day); data.amount_cents = Math.round(Number(data.amount) * 100); delete data.amount;
      await api(`/placements/${form.dataset.placement}/ledger`,data);
    }
  });
});
action(async () => {});
