"use strict";
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = (cents) => new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(cents / 100);
const fact = (label, value) => `<div class="fact"><dt>${escapeHTML(label)}</dt><dd>${escapeHTML(value === null || value === undefined || value === "" ? "Not recorded" : value)}</dd></div>`;
const humanLabel = (text) => String(text).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
const localTime = (value) => value ? new Date(value).toLocaleString("en-US",{timeZone:"America/New_York",dateStyle:"medium",timeStyle:"short"}) + " ET" : "Not recorded";
let state, selected, busy = false;
let recommendationRevision = 0;
let regulationRevision = 0;
let communityQuery = "";
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
  recommendationRevision++;
  $("recommend-results").innerHTML = '<p class="muted">Run Top 3 again to use current availability and ratings.</p>';
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
function pulseBadge(c) {
  const p = c.pulse;
  if (!p) return "No Monday pulse yet";
  const rate = p.rate_changed ? `Rate update: ${p.rate_change_note || "Yes"}` : "Rates: status quo";
  return `Private ${p.private_rooms} · Semi-M ${p.semi_private_male_rooms} · Semi-F ${p.semi_private_female_rooms} · ${rate} (${p.status})`;
}
function renderCommunities() {
  const q = communityQuery.trim().toLowerCase();
  const list = (state?.communities || []).filter((c) => !q || `${c.name} ${c.city} ${c.category || ""}`.toLowerCase().includes(q));
  $("community-list").innerHTML = list.map((c) => `<article class="panel"><h3>${escapeHTML(c.name)}</h3><p>${escapeHTML(c.city)}${c.miles_from_office != null ? ` · ${escapeHTML(c.miles_from_office)} mi` : ""} · ${escapeHTML(c.licensed_beds ?? "Unknown")} licensed beds</p><p><span class="badge">${c.contract_status === "contracted" ? "Contracted: YES" : escapeHTML(humanLabel(c.contract_status || "not_contracted"))}</span> <strong>${escapeHTML(stars(c))}</strong></p>${c.contract_warning ? `<p class="muted"><strong>${escapeHTML(c.contract_warning)}</strong></p>` : ""}${c.owner_rating?.note ? `<p>Tour notes: ${escapeHTML(c.owner_rating.note)}</p>` : ""}${state.can_confirm_placement ? communityControls(c) : ""}<dl>${fact("Monday pulse", pulseBadge(c))}${fact("Pulse channel", `${humanLabel(c.preferred_pulse_channel || "email")}${c.contact_email ? ` · ${c.contact_email}` : ""}${c.contact_sms_phone ? ` · SMS ${c.contact_sms_phone}` : ""}`)}${fact("Rates", [c.private_rate_range && `Private ${c.private_rate_range}`, c.semi_private_rate_range && `Semi ${c.semi_private_rate_range}`, c.community_fee && `Fee ${c.community_fee}`].filter(Boolean).join(" · ") || "Not recorded")}${fact("Source", c.source_url || humanLabel(c.source_kind || "owner_added"))}${fact("Openings", c.availability?.status === "verified" ? `${c.availability.vacancies} human-confirmed, expires ${localTime(c.availability.expires_at)}` : "Unknown; human verification needed")}</dl><form data-availability="${escapeHTML(c.id)}"><label>Human-confirmed openings<input name="vacancies" type="number" min="0" step="1" required></label><label>Verified at (your device timezone)<input name="verified_at" type="datetime-local" required></label><label>Expires at (your device timezone)<input name="expires_at" type="datetime-local" required></label><label>Verification reference<input name="source_ref" required placeholder="Conversation or source reference"></label><button>Record verification</button></form></article>`).join("") || '<p class="muted">No matching facility records yet. Licensed capacity does not establish openings.</p>';
}
function render() {
  const referrals = state.referrals || [], totals = state.briefing?.totals || state.briefing || {};
  $("count").textContent = referrals.filter((r) => r.status !== "Placed").length;
  for (const field of ["contracted", "invoiced", "collected"]) {
    const amount = totals[`${field}_cents`];
    $(field).textContent = Number.isInteger(amount) ? money(amount) : "Not recorded";
  }
  const attention = referrals.filter((r) => r.missing_info?.length || r.attention === "urgent" || r.attention === "human_request");
  const dueCheckins = totals.due_post_placement_checkins || [];
  $("briefing-content").innerHTML = `<h3>Family review</h3>${attention.map((r) => `<div class="activity"><strong>${escapeHTML(r.name)}</strong><p>${r.attention && r.attention !== "routine" ? `${escapeHTML(humanLabel(r.attention))}. ` : ""}${escapeHTML((r.missing_info || []).map(humanLabel).join(", ") || "Human callback needed")}</p><button class="secondary" data-open-case="${escapeHTML(r.id)}">Review family</button></div>`).join("") || '<p>No intake gaps recorded.</p>'}<div class="action-group"><h3>Post-placement check-ins due (Day 7 / 30 / 60)</h3>${dueCheckins.length ? dueCheckins.map((c) => `<div class="activity"><strong>Day ${Number(c.day)} · ${escapeHTML(humanLabel(c.audience))}</strong> (due ${escapeHTML(c.due_date)})<p>${escapeHTML(c.draft_text)}</p></div>`).join("") : '<p class="muted">No post-placement check-ins due today.</p>'}</div><div class="action-group"><h3>Tours and collections</h3><p>${Number(totals.proposed_tours || 0)} proposed tours · ${Number(totals.confirmed_tours || 0)} confirmed tours</p><p>Due now: <strong>${Number.isInteger(totals.due_cents) ? money(totals.due_cents) : "Not recorded"}</strong></p><p>${Number(totals.contracted_communities || 0)} contracted facilities · ${Number(totals.rated_communities || 0)} toured &amp; rated · ${Number(totals.availability_needs_verification || 0)} need availability verification.</p></div>`;
  $("audit").innerHTML = (state.audit || []).slice(0,12).map((event) => `<div class="activity"><strong>${escapeHTML(humanLabel(event.action.replaceAll(".", " ").split(":")[0]))}</strong><br><small>${escapeHTML(localTime(event.at || event.created_at))}</small></div>`).join("") || "No activity recorded yet.";
  $("case-list").innerHTML = referrals.map((r) => `<button class="case-row" data-case="${escapeHTML(r.id)}" aria-pressed="${r.id === selected}"><strong>${escapeHTML(r.name)}</strong><small>${escapeHTML(r.status)} · ${escapeHTML(r.location || "Area not recorded")}</small><br><span class="badge">${escapeHTML(r.contact_status || "active")}</span></button>`).join("") || '<p class="muted">No referrals yet. Save the first record from intake.</p>';
  renderCommunities();
  const connectionNames = {intake:"Referral intake",calendar:"Calendar booking",sender:"Email and text delivery",billing:"Billing provider",monday_pulse:"Monday facility pulse"};
  $("connection-list").innerHTML = Object.entries(state.connections || {}).map(([key,value]) => `<div class="activity"><h3>${escapeHTML(connectionNames[key] || humanLabel(key))}</h3><p>${value === "manual" ? "Manual entry is ready. The intake form connection is still needed." : value === "unconnected" ? "Account connection and an accepted test are still needed." : escapeHTML(humanLabel(value))}</p></div>`).join("");
  if (selected) renderCase();
}
function stars(c) { const r = c.owner_rating || {}; return r.stars ? `${"★".repeat(r.stars)}${"☆".repeat(3 - r.stars)} ${r.label}` : "Not toured / unrated"; }
function communityControls(c) {
  return `<form data-contract="${escapeHTML(c.id)}"><label>Contract<select name="status">${["not_contracted","in_progress","contracted"].map((v) => `<option value="${v}" ${v === (c.contract_status || "not_contracted") ? "selected" : ""}>${humanLabel(v)}</option>`).join("")}</select></label><label>Signed agreement reference<input name="agreement_ref" value="${escapeHTML(c.contract?.agreement_ref || "")}" placeholder="Required when Contracted"></label><button class="secondary">Save contract status</button></form><form data-rating-form="${escapeHTML(c.id)}"><label>Tour notes (private)<input name="note" value="${escapeHTML(c.owner_rating?.note || "")}" placeholder="Cleanliness, care quality, vibe"></label><div class="actions" role="group" aria-label="Your 1 to 3 star tour rating">${[1,2,3].map((n) => `<button type="button" class="secondary" data-rate="${escapeHTML(c.id)}" data-stars="${n}" aria-pressed="${c.owner_rating?.stars === n}">${"★".repeat(n)} (${n})</button>`).join("")}</div></form>`;
}
function recommendationCard(c) { return `<div class="activity"><h3>${escapeHTML(c.name)}</h3><p><strong>${escapeHTML(stars(c))}</strong> · <span class="badge">${c.contract_status === "contracted" ? "Contracted: YES" : "Contracted: NO"}</span></p>${c.contract_warning ? `<p><strong>${escapeHTML(c.contract_warning)}</strong></p>` : ""}<p>${escapeHTML(c.why.join(" · ") || c.city)}</p>${c.owner_rating?.note ? `<p>Tour notes: ${escapeHTML(c.owner_rating.note)}</p>` : ""}<p>${c.availability?.status === "verified" ? `${c.availability.vacancies} human-confirmed openings` : "Openings unknown"}</p><small>Still check: ${escapeHTML(c.checks_needed.join(", "))}</small></div>`; }
function ruleCard(r) {
  const context = (r.context || []).map((x) => `<p class="muted"><strong>${escapeHTML(x.citation)}</strong> ${escapeHTML(x.text)}</p>`).join("");
  return `<article class="panel"><h3>${escapeHTML(r.citation)}</h3><p class="muted">${escapeHTML(r.section)} ${escapeHTML(r.section_title)}${r.context.length ? ` · under ${escapeHTML(r.context.map((x) => x.citation).join(" > "))}` : ""}</p>${context}<p>${escapeHTML(r.text)}</p><small><a href="${escapeHTML(r.official_url)}" target="_blank" rel="noopener noreferrer">Official source</a> · effective ${escapeHTML(r.effective || "see source")} · retrieved ${escapeHTML(localTime(r.retrieved_at))}</small></article>`;
}
function partyStatus(party) { return `${escapeHTML(humanLabel(party.status))}${party.status === "accepts" && party.option ? ` (option ${escapeHTML(party.option)})` : ""}`; }
function tourPlans(r, communityOptions) {
  const plans = (state.tour_plans || []).filter((p) => p.referral_id === r.id);
  const names = Object.fromEntries((state.communities || []).map((c) => [c.id, c.name]));
  return `<div class="action-group"><h3>Plan tours (up to 3 communities)</h3><p class="muted">Builds back-to-back stops and drafts for the family, each community and you. Nothing is sent or booked.</p><form id="tour-plan-form"><fieldset><legend>Communities, in visiting order</legend>${[0,1,2].map((i) => `<label>Stop ${i + 1}<select name="community_${i}" ${i === 0 ? "required" : ""}><option value="">${i === 0 ? "Choose a community" : "None"}</option>${communityOptions}</select></label>`).join("")}</fieldset><div class="two">${[0,1,2].map((i) => `<label>Start option ${i + 1} (your device timezone)<input name="option_${i}" type="datetime-local" ${i === 0 ? "required" : ""}></label>`).join("")}<label>Minutes per tour<input name="tour_minutes" type="number" min="15" max="180" value="45"></label><label>Drive minutes between stops<input name="travel_minutes" type="number" min="0" max="120" value="30"></label></div><button>Prepare tour plan and drafts</button></form>${plans.map((p) => `<div class="activity"><span class="badge">${escapeHTML(humanLabel(p.status))}</span>${p.options.map((o, i) => { const agreed = p.status === "ready_to_book" && p.chosen_option === i + 1; return `<p${agreed ? ' class="chosen"' : ""}><strong>Option ${i + 1}${agreed ? " — agreed" : ""}:</strong> ${o.stops.map((s) => `${escapeHTML(s.community_name)} ${escapeHTML(localTime(s.start_at))}`).join(" · ")} <a href="/api/vhin/tour-plans/${encodeURIComponent(p.id)}/calendar.ics?option=${i + 1}">${agreed ? "Agreed itinerary calendar file" : "Tentative calendar file"}</a></p>`; }).join("")}<p>Family: ${partyStatus(p.parties.family)} · You: ${partyStatus(p.parties.owner)} · ${Object.entries(p.parties.communities).map(([id, v]) => `${escapeHTML(names[id] || "Community")}: ${partyStatus(v)}`).join(" · ")}</p><details><summary>Drafts to review and send yourself</summary>${p.drafts.family ? `<h4>Family email</h4><pre>${escapeHTML(p.drafts.family.family_email)}</pre><h4>Family text</h4><pre>${escapeHTML(p.drafts.family.family_text)}</pre>` : "<p>No family draft: contact is stopped, paused or has no preference.</p>"}${Object.entries(p.drafts.communities).map(([id, d]) => `<h4>${escapeHTML(names[id] || "Community")} ${d.to_email ? `(${escapeHTML(d.to_email)})` : ""}</h4><pre>${escapeHTML(d.email)}</pre>`).join("")}<h4>Your summary</h4><pre>${escapeHTML(p.drafts.owner_summary)}</pre></details>${["awaiting_replies","needs_new_times"].includes(p.status) ? `<form data-tour-response="${escapeHTML(p.id)}"><div class="two"><label>Who replied<select name="who"><option value="family">Family</option><option value="owner">Owner (you)</option>${Object.keys(p.parties.communities).map((id) => `<option value="community:${escapeHTML(id)}">${escapeHTML(names[id] || "Community")}</option>`).join("")}</select></label><label>Reply<select name="response"><option value="accepts">Accepts</option><option value="declines">Declines</option></select></label><label>Option number<input name="option" type="number" min="1" max="${p.options.length}"></label><label>Where the reply came from<input name="source_ref" required placeholder="Text from daughter, 2:10 PM"></label></div><button class="secondary">Record reply</button></form>` : ""}</div>`).join("")}</div>`;
}
function checkinsPanel(placement) {
  const rows = placement.post_placement_checkins || [];
  if (!rows.length) return "";
  return `<div class="action-group"><h4>Post-placement check-in cadence (${escapeHTML(humanLabel(placement.checkin_cadence_status || "active"))})</h4>${rows.map((c) => `<div class="activity"><span class="badge">Day ${Number(c.day)} · ${escapeHTML(humanLabel(c.audience))} · ${escapeHTML(humanLabel(c.status))}</span> <small>Due ${escapeHTML(c.due_date)}</small><p>${escapeHTML(c.draft_text)}</p>${c.status === "pending" ? `<div class="actions"><button type="button" class="secondary" data-checkin="${escapeHTML(placement.id)}" data-day="${Number(c.day)}" data-audience="${escapeHTML(c.audience)}" data-status="completed">Mark sent / done</button><button type="button" class="secondary" data-checkin="${escapeHTML(placement.id)}" data-day="${Number(c.day)}" data-audience="${escapeHTML(c.audience)}" data-status="skipped">Skip</button></div>` : ""}</div>`).join("")}</div>`;
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
    <div class="action-group"><h3>Family follow-up</h3><form id="draft-form"><label>Reason<select name="reason"><option value="incomplete">Incomplete intake</option><option value="no_booking">No tour yet</option><option value="missed_tour">Missed tour</option><option value="completed_tour">Tour completed</option><option value="planning">Planning ahead</option></select></label><label>Message for review<textarea name="body" rows="3" required></textarea></label><button>Save draft</button></form><div>${(r.drafts ?? state.drafts?.filter((d) => d.referral_id === r.id) ?? []).map((d) => `<div class="activity"><span class="badge">${escapeHTML(d.status)}</span><p>${escapeHTML(d.body)}</p></div>`).join("")}</div></div>
    <div class="action-group"><h3>Community comparison</h3><p class="muted">Contracted homes first, then owner 1-3 star tour ratings. Openings and care fit require human confirmation.</p>${[...(state.communities || [])].sort((a,b) => Number(b.contract_status === "contracted") - Number(a.contract_status === "contracted") || (b.owner_rating?.stars || 0) - (a.owner_rating?.stars || 0) || Number(b.city.toLowerCase() === (r.location || "").toLowerCase()) - Number(a.city.toLowerCase() === (r.location || "").toLowerCase())).map((c) => `<div class="activity"><h3>${escapeHTML(c.name)}</h3><p><span class="badge">${c.contract_status === "contracted" ? "Contracted: YES" : "Contracted: NO"}</span> <strong>${escapeHTML(stars(c))}</strong></p>${c.contract_warning ? `<p><strong>${escapeHTML(c.contract_warning)}</strong></p>` : ""}<p>${escapeHTML(c.city)} · ${escapeHTML((c.services || []).join(", ") || "Services need verification")}</p><p>${c.availability?.status === "verified" ? `${c.availability.vacancies} human-confirmed openings` : "Availability unknown"}</p></div>`).join("") || '<p>Add a facility to compare it with this family.</p>'}</div>
    <div class="action-group"><h3>Tour proposal</h3><form id="tour-form"><label>Community<select name="community_id" required><option value="">Choose a community</option>${communities}</select></label><div class="two"><label>Start (your device timezone)<input name="start_at" type="datetime-local" required></label><label>End (your device timezone)<input name="end_at" type="datetime-local" required></label></div><button>Save proposed tour</button></form><div>${(state.tours || []).filter((t) => t.referral_id === r.id).map((t) => `<p>${escapeHTML(localTime(t.start_at))} · ${escapeHTML(t.status)}</p>`).join("")}</div></div>
    ${tourPlans(r, communities)}
    <div class="action-group"><h3>Placement and fee milestones</h3>${placement ? `<dl>${fact("Contracted fee",money(placement.fee_cents))}${fact("Move-in",placement.move_in_date)}${fact("Signed agreement",placement.agreement_ref)}</dl>${placement.installments.map((i) => `<p>Day ${i.day}: <strong>${money(i.amount_cents)}</strong> due ${escapeHTML(i.due_date)}</p>`).join("")}${checkinsPanel(placement)}<form id="ledger-form" data-placement="${escapeHTML(placement.id)}"><div class="two"><label>Record type<select name="kind"><option value="invoiced">Invoice issued</option><option value="collected">Payment received</option></select></label><label>Installment<select name="day"><option value="30">Day 30</option><option value="60">Day 60</option></select></label><label>Amount ($)<input name="amount" type="number" min="0.01" step="0.01" required></label><label>Event date<input name="event_date" type="date" required></label></div><label>Receipt reference<input name="receipt_ref" required></label><button>Record financial evidence</button></form>` : state.can_confirm_placement ? `<form id="placement-form"><label>Community<select name="community_id" required><option value="">Choose a community</option>${communities}</select></label><div class="two"><label>Move-in date<input name="move_in_date" type="date" required></label><label>Agreement signed on<input name="agreement_signed_on" type="date" required></label><label>Total fee ($)<input name="fee" type="number" min="0.01" step="0.01" required></label><label>Signed agreement reference<input name="agreement_ref" required></label></div><label>Agreed refund / proration terms<textarea name="refund_terms" required></textarea></label><button>Confirm move-in and signed terms</button></form>` : `<p class="muted">Only the configured placement owner can record move-in and signed terms.</p>`}</div>`;
}
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => view(button.dataset.view)));
$("refresh").addEventListener("click", () => action(async () => {}));
$("new-case").addEventListener("click", () => { selected = null; $("case-detail").hidden = true; $("intake").hidden = false; });
$("case-list").addEventListener("click", (event) => { const button = event.target.closest("[data-case]"); if (button) { selected = button.dataset.case; render(); } });
if ($("community-filter")) $("community-filter").addEventListener("input", (event) => { communityQuery = event.target.value; renderCommunities(); });
if ($("run-sprint")) $("run-sprint").addEventListener("click", async () => {
  try {
    $("failure").hidden = true;
    const res = await api("/contract-sprint?max_miles=30&limit=5");
    $("sprint-results").innerHTML = res.targets.length ? `<h3>This week's 5 contracting targets (${res.total_uncontracted_in_radius} uncontracted in radius)</h3>` + res.targets.map((c, idx) => `<div class="activity"><strong>${idx + 1}. ${escapeHTML(c.name)}</strong> · ${escapeHTML(c.city)}${c.miles_from_office != null ? ` · ${escapeHTML(c.miles_from_office)} mi` : ""} · ${escapeHTML(c.licensed_beds ?? "?")} beds<br><small>${escapeHTML(c.address || "")} ${escapeHTML(c.contact_phone || "")}</small></div>`).join("") : '<p class="muted">No uncontracted residential targets in this radius.</p>';
  } catch (error) { failure(error); }
});
if ($("gen-pulse")) $("gen-pulse").addEventListener("click", async () => {
  try {
    $("failure").hidden = true;
    const res = await api("/pulse/generate", {});
    $("pulse-results").innerHTML = res.links.length ? `<h3>Monday Pulse Links (${escapeHTML(res.week_iso)} · unsent)</h3>` + res.links.map((l) => `<div class="activity"><strong>${escapeHTML(l.name)}</strong> (${escapeHTML(humanLabel(l.preferred_pulse_channel))})<br><small>${escapeHTML(l.contact_email || l.contact_sms_phone || "Add contact email/SMS")}</small><br><a href="${escapeHTML(l.pulse_url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(l.pulse_url)}</a></div>`).join("") : '<p class="muted">No contracted ALF / AFCH / Memory Care facilities ready for pulse links yet.</p>';
  } catch (error) { failure(error); }
});
document.addEventListener("click", (event) => {
  const openCase = event.target.closest("[data-open-case]");
  if (openCase) { selected = openCase.dataset.openCase; render(); view("cases"); return; }
  const rate = event.target.closest("[data-rate]");
  if (rate) {
    const form = rate.closest("[data-rating-form]");
    const noteInput = form ? form.querySelector("input[name='note']") : null;
    action(async () => { await api(`/communities/${encodeURIComponent(rate.dataset.rate)}/rating`,{stars:Number(rate.dataset.stars), note: noteInput ? noteInput.value : ""}); });
    return;
  }
  const checkin = event.target.closest("[data-checkin]");
  if (checkin) {
    action(async () => { await api(`/placements/${encodeURIComponent(checkin.dataset.checkin)}/checkins/${encodeURIComponent(checkin.dataset.day)}/${encodeURIComponent(checkin.dataset.audience)}`, {status: checkin.dataset.status}); });
    return;
  }
  const button = event.target.closest("[data-transition], [data-contact]");
  if (!button) return;
  action(async () => {
    if (button.dataset.transition) await api(`/referrals/${selected}/transition`,{status:button.dataset.transition,human_confirmed:true});
    else await api(`/referrals/${selected}/contact-events`,{event:button.dataset.contact});
  });
});
async function lookup(form) {
  const data = compact(formData(form));
  try {
    $("failure").hidden = true;
    if (form.id === "recommend-form") {
      const revision = ++recommendationRevision;
      const params = new URLSearchParams(data);
      if (form.querySelector && form.querySelector("input[name='contracted_only']")?.checked) params.set("contracted_only", "true");
      const result = await api(`/recommendations?${params}`);
      if (revision !== recommendationRevision) return;
      $("recommend-results").innerHTML = (result.recommendations || []).map(recommendationCard).join("") || '<p class="muted">No recorded facilities match those criteria.</p>';
      if (result.excluded_unknown_distance) $("recommend-results").innerHTML += `<p class="muted">${Number(result.excluded_unknown_distance)} communities had no recorded distance and were excluded from the mileage limit.</p>`;
    } else if (form.id === "rules-form") {
      const revision = ++regulationRevision;
      const result = await api(`/regulations/FL/search?${new URLSearchParams(data)}`);
      if (revision !== regulationRevision) return;
      $("rules-results").innerHTML = (result.results || []).map(ruleCard).join("") || '<p class="muted">No exact match in the loaded Florida rules. Try another phrase.</p>';
    }
  } catch (error) { failure(error); }
}
document.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.id === "recommend-form" || form.id === "rules-form") return lookup(form);
  const data = compact(formData(form));
  action(async () => {
    if (form.id === "referral-form") {
      if (data.budget) { data.budget_cents = Math.round(Number(data.budget) * 100); delete data.budget; }
      const saved = await api("/referrals",data); selected = saved.id; form.reset();
    } else if (form.id === "edit-referral") {
      const current = state.referrals.find((row) => row.id === selected);
      data.expected_version = current.version;
      if (data.budget) { data.budget_cents = Math.round(Number(data.budget) * 100); delete data.budget; }
      await api(`/referrals/${selected}`,data,"PATCH");
    } else if (form.id === "draft-form") { await api(`/referrals/${selected}/drafts`,data); form.reset(); }
    else if (form.id === "community-form") {
      data.services = (data.services || "").split(",").map((s) => s.trim()).filter(Boolean);
      data.care_levels = [...data.services];
      if (data.licensed_beds) data.licensed_beds = Number(data.licensed_beds);
      if (data.miles_from_office) data.miles_from_office = Number(data.miles_from_office);
      if (data.observed_at) data.observed_at = new Date(data.observed_at).toISOString();
      data.source_kind = data.source_url ? "florida_health_finder" : "owner_added";
      await api("/communities",data); form.reset();
    } else if (form.dataset.availability) {
      data.vacancies = Number(data.vacancies); data.human_confirmed = true;
      data.verified_at = new Date(data.verified_at).toISOString(); data.expires_at = new Date(data.expires_at).toISOString();
      await api(`/communities/${form.dataset.availability}/availability`,data);
    } else if (form.id === "tour-form") {
      data.referral_id = selected;
      data.start_at = new Date(data.start_at).toISOString(); data.end_at = new Date(data.end_at).toISOString();
      await api("/tours",data);
    } else if (form.dataset.contract) {
      await api(`/communities/${encodeURIComponent(form.dataset.contract)}/contract`,{status:data.status, agreement_ref:data.agreement_ref || null, human_confirmed:true});
    } else if (form.id === "tour-plan-form") {
      const community_ids = [0,1,2].map((i) => data[`community_${i}`]).filter(Boolean);
      const options = [0,1,2].map((i) => data[`option_${i}`]).filter(Boolean).map((v) => new Date(v).toISOString());
      await api("/tour-plans",{referral_id:selected, community_ids, options, tour_minutes:Number(data.tour_minutes || 45), travel_minutes:Number(data.travel_minutes || 30)});
    } else if (form.dataset.tourResponse) {
      const [party, community_id] = String(data.who || "").split(":");
      const body = {party, response:data.response, source_ref:data.source_ref};
      if (community_id) body.community_id = community_id;
      if (data.option) body.option = Number(data.option);
      await api(`/tour-plans/${encodeURIComponent(form.dataset.tourResponse)}/responses`, body);
    } else if (form.id === "placement-form") {
      data.referral_id = selected; data.fee_cents = Math.round(Number(data.fee) * 100); delete data.fee; data.terms = "50_50_day30_day60";
      await api("/placements",data);
    } else if (form.id === "ledger-form") {
      data.day = Number(data.day); data.amount_cents = Math.round(Number(data.amount) * 100); delete data.amount;
      await api(`/placements/${form.dataset.placement}/ledger`,data);
    }
  });
});
action(async () => {});
