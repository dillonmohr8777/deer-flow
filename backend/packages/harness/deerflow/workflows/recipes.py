"""One hundred Momentum and twenty personal recipes; all examples are fictional."""

# id | title | inputs | outputs | production brief | acceptance checks
RECIPES = {
    "paid_media": "\n".join(
        [
            (
                "search-ad-variants|"
                "Search ad variants|"
                "offer,audience,keyword_themes|"
                "headlines,descriptions|"
                "Draft search-ad copy grouped by intent using only supplied offers and differentiators.|"
                "Headlines fit 30 characters;Descriptions fit 90 characters;Every claim is supported by the supplied offer"
            ),
            (
                "search-keyword-clusters|"
                "Search keyword clusters|"
                "service_catalog,search_terms,target_region|"
                "intent_clusters,negative_candidates|"
                "Group supplied terms into conversion-intent clusters and propose exclusions with reasons.|"
                "Every source term is assigned or excluded;Exclusions include intent rationale;No invented search volume or performance"
            ),
            (
                "paid-search-structure|"
                "Paid search account structure|"
                "services,regions,conversion_actions|"
                "campaign_blueprint,ad_group_blueprint|"
                "Draft campaign and ad-group separation by service and geography with explicit conversion mapping.|"
                "Each group has one coherent intent;Every region maps to the provided region list;Conversion mapping uses only supplied actions"
            ),
            (
                "meta-creative-brief|"
                "Meta creative testing brief|"
                "product_facts,audience_insights,creative_assets|"
                "creative_concepts,test_hypotheses|"
                "Specify distinct creative angles and controlled hypotheses for existing supplied assets.|"
                "Concepts differ in message and visual treatment;Each hypothesis names one changed variable;No new campaign or spend is implied"
            ),
            (
                "remarketing-sequence|"
                "Remarketing message sequence|"
                "audience_stages,offer_terms,frequency_constraints|"
                "stage_messages,suppression_rules|"
                "Draft stage-aware remarketing messages and exclusions using consent and frequency constraints.|"
                "Each stage has a relevant message;Suppression follows supplied constraints;No unsupported urgency or tracking assumption"
            ),
            (
                "landing-ad-message-match|"
                "Ad to landing page message match|"
                "ad_copy,landing_copy,conversion_goal|"
                "message_gaps,replacement_copy|"
                "Compare supplied ads and landing text then draft specific message-match repairs.|"
                "Each gap quotes or identifies source text;Replacements preserve actual offer terms;The conversion action is consistent throughout"
            ),
            (
                "search-term-waste-review|"
                "Search term waste review|"
                "term_performance,qualified_lead_definition,observation_window|"
                "review_findings,decision_drafts|"
                "Review supplied term-level results and distinguish observed waste from sparse-data uncertainty.|"
                "Recommendations cite supplied rows;Missing conversions are not treated as zero;No live exclusion or bid update is executed"
            ),
            (
                "creative-fatigue-review|"
                "Creative fatigue review|"
                "creative_history,delivery_metrics,comparison_periods|"
                "fatigue_signals,refresh_briefs|"
                "Assess whether supplied creative trends justify refresh hypotheses while separating seasonality and sample-size limits.|"
                "Signals reference matched periods;Refresh briefs identify the tested angle;Missing delivery data is flagged"
            ),
            (
                "conversion-event-map|"
                "Conversion event map|"
                "funnel_steps,event_inventory,attribution_requirements|"
                "event_mapping,validation_steps|"
                "Draft measurement mapping from each funnel action to existing events and verification steps.|"
                "Each funnel step has an event or explicit gap;Duplicate events are identified;No conversion goal is changed"
            ),
            (
                "paid-media-experiment-plan|"
                "Paid media experiment plan|"
                "hypothesis,current_setup,success_criteria|"
                "experiment_design,stop_rules|"
                "Define a controlled draft test with eligibility, decision thresholds and bounded stopping criteria.|"
                "One primary hypothesis is isolated;Stop rules use supplied success criteria;Budget changes remain proposals for approval"
            ),
        ]
    ),
    "seo": "\n".join(
        [
            (
                "seo-title-rewrite|"
                "SEO title rewrites|"
                "page_inventory,search_intent,brand_rules|"
                "title_tags,change_rationale|"
                "Use fetched public sources and page inventory to draft intent-specific page titles.|"
                "Titles accurately reflect their pages;No fabricated ranking or traffic claim;Duplicate intent and titles are identified"
            ),
            (
                "seo-meta-rewrite|"
                "SEO meta descriptions|"
                "page_inventory,offer_facts,style_rules|"
                "meta_descriptions,cta_rationale|"
                "Draft useful meta descriptions grounded in fetched pages and supplied offer facts.|"
                "Descriptions fit 160 characters;Each description describes its actual page;Calls to action preserve supplied offer terms"
            ),
            (
                "seo-heading-review|"
                "SEO heading hierarchy review|"
                "page_outline,primary_topics,reader_questions|"
                "heading_repairs,coverage_gaps|"
                "Compare fetched page text with the supplied outline and propose a logical heading structure.|"
                "Heading levels form a usable hierarchy;Gaps map to supplied reader questions;No invented page content is cited"
            ),
            (
                "seo-internal-link-plan|"
                "Internal linking plan|"
                "page_catalog,priority_pages,anchor_constraints|"
                "link_opportunities,anchor_drafts|"
                "Draft internal links among provided pages using topical relevance and descriptive anchors.|"
                "Every link targets a supplied page;Anchor text describes the destination;No unrelated client or external domain is introduced"
            ),
            (
                "seo-local-service-plan|"
                "Local service page plan|"
                "service_area,service_facts,local_proof|"
                "page_sections,proof_gaps|"
                "Plan a service-area page from factual supplied service coverage and fetched public sources.|"
                "Geographic claims use supplied coverage;Proof gaps remain explicit;No invented reviews or local offices"
            ),
            (
                "seo-faq-coverage|"
                "SEO FAQ coverage|"
                "customer_questions,current_answers,product_constraints|"
                "faq_drafts,unanswered_questions|"
                "Draft concise FAQs and identify questions that require missing business facts.|"
                "Answers follow supplied constraints;Unanswerable questions are kept as gaps;No fabricated legal or product assurance"
            ),
            (
                "seo-cannibalization-review|"
                "Search intent overlap review|"
                "page_targets,existing_copy,priority_urls|"
                "overlap_findings,consolidation_drafts|"
                "Compare provided targets and fetched content for overlapping intent and propose draft remediation.|"
                "Overlap identifies both relevant pages;Remediation preserves distinct useful intent;No rankings are inferred without data"
            ),
            (
                "seo-schema-plan|"
                "Structured data implementation plan|"
                "page_types,verified_entities,existing_markup|"
                "schema_requirements,validation_cases|"
                "Specify eligible structured data fields and validation cases without manufacturing missing entity facts.|"
                "Fields correspond to verified entity data;Unsupported rich-result claims are excluded;Missing required values are listed"
            ),
            (
                "seo-content-refresh|"
                "SEO content refresh brief|"
                "existing_article,updated_facts,target_intent|"
                "revision_brief,source_notes|"
                "Identify outdated statements against fetched sources and produce a sourced refresh brief.|"
                "Each factual change maps to a source;Useful existing content is preserved;Dates and unknowns remain distinguishable"
            ),
            (
                "seo-aeo-answer-plan|"
                "Answer engine content plan|"
                "buyer_questions,verified_answers,content_inventory|"
                "answer_blocks,placement_plan|"
                "Draft directly answerable content blocks and placements using supplied knowledge and fetched sources.|"
                "Answers are concise and source-backed;Each placement identifies an existing page;No visibility uplift is promised"
            ),
        ]
    ),
    "content": "\n".join(
        [
            (
                "editorial-calendar|"
                "Editorial calendar|"
                "business_goals,topics,publishing_constraints|"
                "calendar_entries,content_dependencies|"
                "Draft a sequenced editorial calendar with audiences, objectives and required source material.|"
                "Entries connect to supplied business goals;Publishing constraints are respected;Missing source assets are identified"
            ),
            (
                "blog-outline|"
                "Research-backed blog outline|"
                "reader_problem,source_notes,desired_action|"
                "article_outline,research_gaps|"
                "Build a practical article outline with claims tied to supplied sources and unanswered research needs.|"
                "Sections address the reader problem;Claims map to source notes;The next action is appropriate to the article"
            ),
            (
                "short-video-script|"
                "Short video script|"
                "core_message,verified_facts,production_constraints|"
                "script_beats,shot_notes|"
                "Draft a short-form script with hook, evidence, payoff and feasible shot notes.|"
                "Script supports one clear message;Shots fit supplied production constraints;All factual statements use supplied facts"
            ),
            (
                "video-hook-variants|"
                "Short video hook variants|"
                "video_topic,audience_problem,tone_limits|"
                "hook_variants,selection_notes|"
                "Draft distinct opening hooks for the same video with an honest payoff promise.|"
                "Hooks use distinct angles;The promised payoff exists in the topic;No fabricated urgency or results"
            ),
            (
                "carousel-storyboard|"
                "Educational carousel storyboard|"
                "lesson,reader_level,brand_voice|"
                "slide_copy,visual_instructions|"
                "Translate a supplied lesson into a coherent carousel with one purpose per slide.|"
                "Slides build one clear argument;Text fits the supplied reader level;Visual instructions do not invent logos or proof"
            ),
            (
                "social-caption-drafts|"
                "Social caption drafts|"
                "asset_description,post_goal,approved_claims|"
                "caption_variants,accessibility_notes|"
                "Draft captions for an existing described asset with descriptive accessibility notes.|"
                "Captions match the asset;Claims are limited to approved facts;Accessibility notes describe visible content without guessing"
            ),
            (
                "customer-story-draft|"
                "Customer story draft|"
                "approved_case_facts,customer_quote_permissions,story_goal|"
                "story_sections,approval_gaps|"
                "Draft a customer story that separates confirmed facts, permitted quotes and approval gaps.|"
                "Every result comes from approved case facts;Quote permissions are honored;Missing consent is flagged before publication"
            ),
            (
                "content-repurpose-plan|"
                "Content repurposing plan|"
                "source_asset,target_channels,asset_constraints|"
                "repurposed_briefs,production_tasks|"
                "Adapt an existing source asset for different channels with format-specific briefs.|"
                "Each brief retains source meaning;Channel formats are differentiated;Required new assets are explicit"
            ),
            (
                "newsletter-draft|"
                "Newsletter issue draft|"
                "reader_segment,approved_updates,newsletter_goal|"
                "newsletter_sections,subject_lines|"
                "Draft a useful newsletter from approved updates with relevant subject lines and clear action.|"
                "Updates are accurately summarized;Subject lines reflect actual content;No email is sent"
            ),
            (
                "content-claim-audit|"
                "Content claim audit|"
                "draft_copy,source_evidence,claim_policy|"
                "claim_findings,corrected_copy|"
                "Audit supplied copy for unsupported claims and draft narrowly supported alternatives.|"
                "Findings identify the exact claim;Corrections preserve supported meaning;Unresolved claims remain marked for review"
            ),
        ]
    ),
    "web": "\n".join(
        [
            (
                "homepage-message-review|"
                "Homepage message review|"
                "positioning,homepage_copy,conversion_goal|"
                "message_findings,revised_sections|"
                "Inspect public page evidence and draft clearer homepage value proposition and action hierarchy.|"
                "Revisions preserve positioning facts;Primary action matches the conversion goal;Findings cite actual supplied or fetched copy"
            ),
            (
                "landing-page-wireframe|"
                "Landing page wireframe brief|"
                "offer_details,buyer_objections,required_elements|"
                "section_sequence,content_requirements|"
                "Plan a conversion-focused landing page with proof and objection handling grounded in public evidence.|"
                "Every required element has a placement;Proof comes from supplied evidence;No conversion-rate improvement is promised"
            ),
            (
                "mobile-page-review|"
                "Mobile page usability review|"
                "page_description,known_device_issues,priority_tasks|"
                "usability_findings,repair_requirements|"
                "Assess actual fetched page evidence and supplied mobile issues without claiming a physical device test.|"
                "Findings distinguish evidence from hypotheses;Repairs support supplied priority tasks;Unobserved device behavior stays unverified"
            ),
            (
                "website-accessibility-brief|"
                "Website accessibility repair brief|"
                "page_structure,known_a11y_issues,interaction_requirements|"
                "repair_spec,manual_checks|"
                "Draft accessibility repairs and manual checks from fetched content and known interaction issues.|"
                "Each repair maps to a specific issue;Keyboard and screen-reader checks are explicit;No WCAG certification is asserted"
            ),
            (
                "form-conversion-review|"
                "Lead form review|"
                "form_fields,completion_obstacles,data_requirements|"
                "field_repairs,validation_messages|"
                "Review form friction and draft field/validation changes consistent with required data.|"
                "Required data is retained;Validation messages explain recovery;No real submission or consent change occurs"
            ),
            (
                "navigation-ia-plan|"
                "Navigation information architecture|"
                "page_inventory,user_tasks,organization_rules|"
                "navigation_structure,label_drafts|"
                "Organize supplied pages around user tasks with clear navigation labels.|"
                "Every retained page has a location;Labels describe destination content;Priority user tasks remain discoverable"
            ),
            (
                "website-qa-checklist|"
                "Website release QA checklist|"
                "release_changes,supported_devices,critical_paths|"
                "qa_cases,release_gates|"
                "Turn actual release changes into reproducible browser and device QA cases.|"
                "Each change has a relevant check;Critical paths include expected outcomes;Prepared checks are not presented as executed"
            ),
            (
                "page-copy-rewrite|"
                "Service page copy rewrite|"
                "existing_copy,service_facts,voice_guide|"
                "rewritten_sections,proof_requests|"
                "Rewrite an existing service page for clarity without expanding unsupported promises.|"
                "Service claims match supplied facts;Reader concerns are addressed;Missing proof is requested explicitly"
            ),
            (
                "website-migration-plan|"
                "Website migration plan|"
                "url_inventory,migration_constraints,tracking_inventory|"
                "migration_steps,readback_checks|"
                "Draft URL, content, measurement and rollback migration steps with downstream readback.|"
                "Every source URL is accounted for;Tracking checks precede launch claims;Rollback requirements are concrete"
            ),
            (
                "website-performance-brief|"
                "Website performance repair brief|"
                "measured_metrics,asset_inventory,delivery_constraints|"
                "prioritized_repairs,validation_plan|"
                "Prioritize performance improvements from supplied measurements and assets without inventing scores.|"
                "Priorities cite measured bottlenecks;Constraints shape repairs;Post-change validation remains required"
            ),
        ]
    ),
    "brand": "\n".join(
        [
            (
                "positioning-statement|"
                "Positioning statement draft|"
                "buyer_segment,verified_differentiators,category_context|"
                "positioning_options,proof_requirements|"
                "Draft concise positioning alternatives anchored in the actual audience and differentiators.|"
                "Options identify a concrete buyer;Differentiators are supported;Unproven superiority claims are excluded"
            ),
            (
                "brand-voice-guide|"
                "Brand voice guide|"
                "approved_examples,audience_context,language_constraints|"
                "voice_principles,before_after_examples|"
                "Derive usable writing rules and editing examples from approved source writing.|"
                "Principles map to supplied examples;Language constraints are enforced;Examples are fictional rather than client quotes"
            ),
            (
                "value-proposition-map|"
                "Value proposition map|"
                "buyer_jobs,service_capabilities,known_objections|"
                "value_messages,objection_responses|"
                "Map buyer needs to proven capabilities and honest responses to objections.|"
                "Every value statement maps to a capability;Objections receive specific responses;Unknown capabilities remain gaps"
            ),
            (
                "campaign-narrative|"
                "Campaign narrative brief|"
                "campaign_goal,approved_product_story,audience_tension|"
                "narrative_arc,message_hierarchy|"
                "Draft a campaign narrative connecting audience tension to supported product value.|"
                "Story follows approved facts;Messages support one campaign goal;No invented customer story or outcome"
            ),
            (
                "brand-asset-checklist|"
                "Brand asset production checklist|"
                "asset_inventory,approved_style,delivery_channels|"
                "asset_requirements,qa_rules|"
                "Specify missing and reusable brand assets for named delivery channels.|"
                "Requirements distinguish existing from missing assets;Approved style is retained;No logos are redrawn or fabricated"
            ),
            (
                "presentation-storyline|"
                "Presentation storyline|"
                "presentation_goal,source_material,audience_decisions|"
                "slide_sequence,speaker_notes|"
                "Arrange supplied material into a decision-oriented deck storyline and concise notes.|"
                "Every slide has a specific purpose;Assertions use source material;The requested decision is explicit"
            ),
            (
                "proposal-design-brief|"
                "Proposal design brief|"
                "proposal_content,brand_assets,review_requirements|"
                "layout_brief,content_flags|"
                "Draft a feasible proposal layout using exact supplied assets and content hierarchy.|"
                "Assets are referenced without alteration;Terms remain faithful to supplied content;Review-required gaps remain visible"
            ),
            (
                "creative-concept-review|"
                "Creative concept review|"
                "concept_descriptions,brand_rules,campaign_objective|"
                "concept_assessments,revision_directions|"
                "Evaluate competing concepts for message clarity, brand fit and execution feasibility.|"
                "Each assessment uses a stated criterion;Revisions preserve the objective;Unseen visual details are not invented"
            ),
            (
                "music-release-content|"
                "Music release content brief|"
                "approved_artist_bio,release_facts,content_channels|"
                "release_messages,content_assets|"
                "Draft music-release messaging and asset briefs grounded in approved artist and release information.|"
                "Release facts are accurate;Artist voice follows approved context;No posting or distribution is implied"
            ),
            (
                "book-promotion-brief|"
                "Book promotion brief|"
                "approved_synopsis,reader_profile,release_constraints|"
                "promotion_angles,copy_drafts|"
                "Draft book promotion angles that reflect the actual synopsis and reader expectations.|"
                "Angles accurately represent the synopsis;Release constraints are respected;No fabricated review or award"
            ),
        ]
    ),
    "reporting": "\n".join(
        [
            (
                "weekly-client-summary|"
                "Weekly client performance summary|"
                "metric_export,comparison_window,client_goals|"
                "performance_notes,next_actions|"
                "Summarize supplied weekly results and decision-relevant changes with explicit data gaps.|"
                "Comparisons use matched windows;Missing metrics remain unknown;Actions follow observed evidence"
            ),
            (
                "monthly-marketing-report|"
                "Monthly marketing report draft|"
                "channel_exports,reporting_period,agreed_kpis|"
                "report_sections,decision_requests|"
                "Draft a monthly narrative connecting channel results to agreed KPIs and decisions.|"
                "All KPIs use supplied measurements;Channel periods are aligned;Unmeasured business impact is not invented"
            ),
            (
                "lead-quality-analysis|"
                "Lead quality analysis|"
                "lead_records,qualification_rules,source_mapping|"
                "quality_findings,followup_questions|"
                "Apply supplied qualification rules to lead records and separate source uncertainty.|"
                "Rules are applied consistently;Source ambiguity is explicit;Personal details are not needlessly repeated"
            ),
            (
                "attribution-gap-review|"
                "Attribution gap review|"
                "conversion_records,tracking_design,known_gaps|"
                "gap_findings,validation_tasks|"
                "Explain supported attribution gaps and draft tests that distinguish competing causes.|"
                "Findings refer to actual records;Alternative causes remain hypotheses;No unsupported revenue attribution"
            ),
            (
                "analytics-anomaly-review|"
                "Analytics anomaly review|"
                "time_series,change_log,comparison_rules|"
                "anomaly_findings,investigation_steps|"
                "Identify noteworthy supplied data changes and sequence checks before causal conclusions.|"
                "Anomalies use stated comparison rules;Change logs inform hypotheses;Correlation is not presented as causation"
            ),
            (
                "campaign-postmortem|"
                "Campaign postmortem draft|"
                "campaign_results,original_hypothesis,execution_notes|"
                "lessons,followup_tests|"
                "Draft a factual postmortem separating results, implementation deviations and next hypotheses.|"
                "Results trace to provided data;Deviations are identified;Lessons do not claim unsupported causality"
            ),
            (
                "reporting-metric-dictionary|"
                "Marketing metric dictionary|"
                "metric_names,source_definitions,business_questions|"
                "metric_definitions,ambiguity_flags|"
                "Create a consistent dictionary using actual source definitions and business questions.|"
                "Definitions identify source and unit;Ambiguous metrics are flagged;Distinct metrics are not silently merged"
            ),
            (
                "forecast-assumptions-review|"
                "Forecast assumptions review|"
                "forecast_inputs,known_constraints,sensitivity_ranges|"
                "assumption_findings,scenario_requirements|"
                "Review a supplied forecast's assumptions and specify bounded scenarios without fabricating certainty.|"
                "Assumptions are distinguished from actuals;Scenarios use supplied ranges;No financial guarantee is made"
            ),
            (
                "dashboard-specification|"
                "Reporting dashboard specification|"
                "stakeholder_questions,data_sources,refresh_constraints|"
                "dashboard_requirements,data_gaps|"
                "Specify useful views and data dependencies for actual stakeholder decisions.|"
                "Each view answers a supplied question;Refresh limits are stated;Unavailable data is marked rather than faked"
            ),
            (
                "experiment-result-summary|"
                "Experiment result summary|"
                "test_results,predefined_criteria,quality_caveats|"
                "result_interpretation,decision_draft|"
                "Interpret supplied experimental results using predefined criteria and caveats.|"
                "Criteria are applied without post hoc substitution;Sample limitations remain explicit;The decision remains a draft"
            ),
        ]
    ),
    "sales": "\n".join(
        [
            (
                "prospect-research-brief|"
                "Prospect research brief|"
                "prospect_facts,service_fit,known_needs|"
                "fit_findings,research_questions|"
                "Prepare a factual fit assessment from supplied prospect evidence without inventing contact details.|"
                "Fit follows supported needs;Unknown facts remain questions;No outreach is sent"
            ),
            (
                "personalized-outreach-draft|"
                "Personalized outreach draft|"
                "verified_business_facts,approved_pitch,signature_text|"
                "email_draft,personalization_notes|"
                "Draft a concise business-specific outreach message using the exact supplied pitch and signature.|"
                "Personalization cites verified facts;Signature appears exactly once;No sending or unsupported promise"
            ),
            (
                "discovery-question-plan|"
                "Discovery question plan|"
                "prospect_context,service_scope,qualification_goals|"
                "discovery_questions,decision_mapping|"
                "Draft a prioritized discovery conversation tied to actual qualification decisions.|"
                "Questions avoid assuming unknown facts;Each question maps to a decision;Scope matches offered services"
            ),
            (
                "service-proposal-draft|"
                "Service proposal draft|"
                "agreed_scope,approved_terms,delivery_constraints|"
                "proposal_sections,open_terms|"
                "Draft a proposal from confirmed scope and terms while exposing unresolved decisions.|"
                "Scope matches the supplied agreement;Terms are not invented;Missing commitments remain open"
            ),
            (
                "statement-of-work-draft|"
                "Statement of work draft|"
                "deliverables,approved_timeline,acceptance_requirements|"
                "scope_sections,acceptance_clauses|"
                "Draft deliverables, dependencies and acceptance language from supplied commitments.|"
                "Deliverables are measurable;Timeline follows approved dates;No unapproved legal commitment is added"
            ),
            (
                "objection-response-library|"
                "Sales objection response library|"
                "buyer_objections,approved_evidence,service_limits|"
                "response_drafts,proof_gaps|"
                "Draft clear responses backed by approved evidence while respecting service limitations.|"
                "Responses address the actual objection;Evidence is accurately represented;Unknown guarantees are excluded"
            ),
            (
                "lead-handoff-brief|"
                "Lead handoff brief|"
                "qualification_notes,contact_permissions,next_step|"
                "handoff_summary,missing_information|"
                "Prepare a factual sales handoff with permission boundaries and a clear next action.|"
                "Summary preserves qualification facts;Contact permissions remain explicit;Unconfirmed next steps are marked"
            ),
            (
                "followup-email-draft|"
                "Sales follow-up email draft|"
                "conversation_notes,confirmed_commitments,signature_text|"
                "followup_copy,commitment_checklist|"
                "Draft a follow-up addressing each supplied conversation point and confirmed commitment.|"
                "Every material point is addressed;Signature appears exactly once;No invented promise or sending"
            ),
            (
                "competitive-pitch-review|"
                "Competitive pitch review|"
                "pitch_draft,verified_competitor_facts,approved_claims|"
                "pitch_findings,corrected_messages|"
                "Review comparative language for specificity and factual support.|"
                "Comparisons use verified facts;Unsupported superiority is removed;Competitor identities remain distinct"
            ),
            (
                "partnership-brief|"
                "Partnership opportunity brief|"
                "partner_capabilities,mutual_goals,known_constraints|"
                "partnership_options,validation_questions|"
                "Draft mutually useful partnership options and clarify unresolved operating assumptions.|"
                "Options map to both parties' capabilities;Constraints are respected;No agreement is represented as signed"
            ),
        ]
    ),
    "operations": "\n".join(
        [
            (
                "client-onboarding-plan|"
                "Client onboarding plan|"
                "signed_scope,required_access,delivery_milestones|"
                "onboarding_tasks,access_gaps|"
                "Draft a scoped onboarding sequence that separates access, source material and delivery dependencies.|"
                "Tasks follow signed scope;Credentials are never requested in plain output;Milestone dependencies are explicit"
            ),
            (
                "client-identity-reconciliation|"
                "Client identity reconciliation|"
                "registry_records,incoming_references,matching_rules|"
                "identity_findings,review_queue|"
                "Compare incoming names with canonical records and flag ambiguity without merging clients.|"
                "Each match cites a canonical record;Ambiguous names remain separate;No record is altered"
            ),
            (
                "meeting-action-register|"
                "Meeting action register|"
                "meeting_notes,confirmed_owners,agreed_dates|"
                "action_items,unassigned_questions|"
                "Extract confirmed actions and unresolved ownership from meeting notes.|"
                "Actions preserve agreed meaning;Owners and dates are not inferred;Unassigned work remains explicit"
            ),
            (
                "project-dependency-map|"
                "Project dependency map|"
                "project_tasks,resource_constraints,deadline_requirements|"
                "dependency_links,critical_questions|"
                "Map actual task dependencies and blockers into a feasible draft plan.|"
                "Dependencies reference supplied tasks;Constraints are considered;Unsupported dates remain unresolved"
            ),
            (
                "standard-operating-procedure|"
                "Standard operating procedure draft|"
                "process_notes,required_checks,authority_rules|"
                "procedure_steps,exception_paths|"
                "Draft a repeatable operating procedure with evidence checks and escalation conditions.|"
                "Steps are actionable and ordered;Checks precede completion claims;Authority rules govern exceptions"
            ),
            (
                "client-status-update|"
                "Client status update draft|"
                "verified_work_status,open_blockers,confirmed_next_steps|"
                "status_copy,approval_requests|"
                "Draft a concise client update that distinguishes prepared, reviewed and delivered work.|"
                "Each status matches supplied evidence;Blockers have specific effects;Unconfirmed delivery is not claimed"
            ),
            (
                "delivery-acceptance-checklist|"
                "Delivery acceptance checklist|"
                "deliverable_spec,acceptance_owner,verification_requirements|"
                "acceptance_cases,missing_evidence|"
                "Create acceptance checks tied to actual deliverable requirements and downstream readback.|"
                "Every requirement has a check;Checks define observable outcomes;Missing proof blocks acceptance"
            ),
            (
                "service-capacity-review|"
                "Service capacity review|"
                "work_queue,available_capacity,priority_rules|"
                "capacity_findings,rescheduling_drafts|"
                "Review supplied workload against actual available capacity and priority rules.|"
                "Capacity calculations use supplied units;Conflicts cite concrete tasks;No deadline change is executed"
            ),
            (
                "invoice-support-brief|"
                "Invoice support brief|"
                "approved_work_records,billing_terms,delivery_receipts|"
                "invoice_notes,receipt_gaps|"
                "Prepare billing-support notes from approved work and verified delivery receipts.|"
                "Charges follow supplied terms;Delivery evidence is referenced;No invoice is sent or payment taken"
            ),
            (
                "incident-communication-draft|"
                "Incident communication draft|"
                "confirmed_incident_facts,affected_services,approved_response|"
                "incident_copy,unknowns|"
                "Draft a precise service-incident update distinguishing confirmed impact and unknowns.|"
                "Impact follows confirmed facts;Recovery is not claimed without proof;No unsupported timeline promise"
            ),
        ]
    ),
    "research": "\n".join(
        [
            (
                "official-release-review|"
                "Official software release review|"
                "release_question,compatibility_constraints,current_versions|"
                "verified_changes,adoption_gaps|"
                "Study supplied official URLs and separate released capabilities from previews and compatibility assumptions.|"
                "Each change cites an actual official source;Version constraints are checked;Unverified capabilities remain gaps"
            ),
            (
                "vendor-capability-comparison|"
                "Vendor capability comparison|"
                "required_capabilities,comparison_criteria,known_environment|"
                "comparison_findings,validation_tasks|"
                "Compare vendors using fetched primary material and the same required capabilities.|"
                "Criteria are applied consistently;Availability differs from tested integration;Missing usage or billing stays unknown"
            ),
            (
                "documentation-integration-brief|"
                "Documentation integration brief|"
                "integration_goal,existing_stack,security_constraints|"
                "implementation_requirements,contract_questions|"
                "Turn fetched official documentation into version-specific integration requirements.|"
                "API contracts come from fetched primary docs;Stack compatibility is explicit;No invented SDK method"
            ),
            (
                "public-business-audit|"
                "Public business presence audit|"
                "business_identity,audit_goal,verified_offerings|"
                "presence_findings,improvement_briefs|"
                "Review supplied public sources for factual business-presence gaps and prepare draft repairs.|"
                "Business identity is preserved;Findings reference observed content;No live business profile is modified"
            ),
            (
                "source-fact-check|"
                "Primary source fact check|"
                "claims_to_check,source_requirements,decision_context|"
                "claim_assessments,unresolved_claims|"
                "Check supplied claims against fetched primary sources and preserve uncertainty.|"
                "Each assessment identifies evidence;Unsupported claims remain unresolved;Publication dates and event dates are distinguished"
            ),
            (
                "browser-workflow-qa-brief|"
                "Browser workflow QA brief|"
                "workflow_description,expected_states,known_constraints|"
                "qa_findings,verification_steps|"
                "Inspect public browser evidence and draft state-by-state checks without executing protected actions.|"
                "Findings reflect actual returned pages;Protected steps remain proposals;Terminal transport status is not useful-output proof"
            ),
            (
                "market-research-synthesis|"
                "Market research synthesis|"
                "provided_research,target_market,decision_question|"
                "research_themes,decision_implications|"
                "Synthesize supplied evidence into decision-relevant themes without estimating missing market size.|"
                "Themes trace to supplied research;Uncertainty and conflicting evidence remain visible;No invented market statistics"
            ),
            (
                "buyer-persona-evidence|"
                "Evidence-backed buyer profile|"
                "interview_notes,verified_behavior,service_context|"
                "buyer_profile,evidence_gaps|"
                "Draft an evidence-backed buyer profile that separates observed behavior from hypotheses.|"
                "Profile facts map to supplied evidence;Hypotheses are labeled;No demographic stereotype is treated as fact"
            ),
            (
                "research-source-register|"
                "Research source register|"
                "source_records,quality_criteria,research_objective|"
                "source_assessments,followup_sources|"
                "Organize supplied references by reliability, relevance and missing provenance.|"
                "Every source has a provenance assessment;Quality criteria are applied consistently;Missing dates or authors remain unknown"
            ),
            (
                "tool-pilot-evaluation-plan|"
                "Tool pilot evaluation plan|"
                "pilot_goal,heldout_tasks,allowed_limits|"
                "evaluation_protocol,acceptance_gates|"
                "Design a fair bounded pilot using identical workloads and observable useful outcomes.|"
                "Comparisons share held-out tasks;Limits and stopping conditions are explicit;Vendor leaderboards are separate from local results"
            ),
        ]
    ),
    "development": "\n".join(
        [
            (
                "bug-reproduction-brief|"
                "Bug reproduction brief|"
                "observed_behavior,expected_behavior,environment_facts|"
                "reproduction_steps,diagnostic_questions|"
                "Draft a minimal reproduction from actual observations and identify missing diagnostic evidence.|"
                "Steps preserve the observed trigger;Expected behavior is explicit;No unobserved execution is claimed"
            ),
            (
                "api-contract-review|"
                "API contract review|"
                "endpoint_contracts,consumer_requirements,authorization_rules|"
                "contract_findings,regression_cases|"
                "Review actual API contracts for schema, status, ownership and retry behavior.|"
                "Findings identify the exact contract field;Owner boundaries are covered;Retries account for uncertain side effects"
            ),
            (
                "security-boundary-review|"
                "Application security boundary review|"
                "trust_boundaries,known_code_behavior,threat_scope|"
                "boundary_findings,verification_cases|"
                "Assess stated trust boundaries for actionable defects without inventing exploited vulnerabilities.|"
                "Findings connect trigger to impact;Authority and ownership are explicit;Unverified exploitability remains qualified"
            ),
            (
                "test-plan-generation|"
                "Change-specific test plan|"
                "change_description,critical_invariants,existing_coverage|"
                "test_cases,coverage_gaps|"
                "Draft regression tests that exercise the changed invariant and meaningful failure paths.|"
                "Cases test behavior rather than mirror code;Failures and cancellation are covered;Existing coverage is distinguished from proposed tests"
            ),
            (
                "pull-request-description|"
                "Pull request description draft|"
                "verified_diff,test_results,reviewer_context|"
                "pr_description,validation_limits|"
                "Draft a reviewer-oriented PR description grounded in the final diff and actual checks.|"
                "Description explains resulting behavior;Only executed checks are reported as passed;Known limits remain explicit"
            ),
            (
                "dependency-upgrade-review|"
                "Dependency upgrade review|"
                "dependency_changes,locked_versions,compatibility_notes|"
                "upgrade_findings,validation_matrix|"
                "Review supplied upgrade changes and identify concrete compatibility checks without changing locks.|"
                "Findings use exact versions;Transitive constraints are considered;No successful install or build is invented"
            ),
            (
                "release-readiness-review|"
                "Application release readiness review|"
                "release_evidence,required_gates,known_limitations|"
                "readiness_findings,remaining_gates|"
                "Assess actual build, test, install and useful-output evidence against release gates.|"
                "Prepared and installed states remain distinct;Each required gate has evidence or a gap;No deployment is claimed"
            ),
            (
                "database-migration-review|"
                "Database migration review|"
                "migration_spec,data_invariants,recovery_constraints|"
                "migration_findings,rollback_checks|"
                "Review proposed data changes for invariants, restart safety and recovery requirements.|"
                "Data invariants are covered;Partial failure and rollback are explicit;No production migration occurs"
            ),
            (
                "agent-lifecycle-review|"
                "Agent lifecycle review|"
                "run_state_machine,admission_rules,recovery_behavior|"
                "lifecycle_findings,race_test_cases|"
                "Review agent admissions and completion for duplicate work, ownership races and truthful status.|"
                "Every transition names its authority;Uncertain work is not labeled completed;Same-worker concurrency and restart are tested"
            ),
            (
                "mobile-qa-plan|"
                "Mobile app QA plan|"
                "app_flows,supported_viewports,accessibility_requirements|"
                "device_test_cases,acceptance_gates|"
                "Draft practical phone, tablet and desktop QA with input, output and accessibility readback.|"
                "Cases cover 390 768 and 1440 widths;Touch targets and overflow are checked;A planned device test is not claimed as executed"
            ),
        ]
    ),
}

BROWSER_IDS = {
    "website-accessibility-brief",
    "official-release-review",
    "mobile-page-review",
    "homepage-message-review",
    "source-fact-check",
    "landing-page-wireframe",
    "vendor-capability-comparison",
    "browser-workflow-qa-brief",
    "documentation-integration-brief",
    "public-business-audit",
}

PERSONAL_RECIPES = "\n".join(
    [
        (
            "novel-chapter-continuity|"
            "Novel chapter continuity review|"
            "chapter_text,continuity_notes,character_facts|"
            "continuity_findings,revision_suggestions|"
            "Review a supplied fictional chapter against existing character and timeline facts without rewriting the author's canon.|"
            "Findings cite supplied chapter details;Character and timeline facts are preserved;Unresolved canon remains a question"
        ),
        (
            "manuscript-line-edit|"
            "Manuscript line edit|"
            "manuscript_excerpt,author_voice,editing_constraints|"
            "edited_passages,editorial_notes|"
            "Draft precise line edits that preserve meaning and the author's supplied voice.|"
            "Edits preserve intended meaning;Voice follows the supplied examples;No unsupported plot fact is added"
        ),
        (
            "novel-scene-outline|"
            "Novel scene outline|"
            "scene_purpose,established_plot,character_motivations|"
            "scene_beats,continuity_checks|"
            "Outline a scene with clear conflict and payoff using only the established fictional plot.|"
            "Beats serve the scene purpose;Motivations match established characters;New canon is labeled as a proposal"
        ),
        (
            "character-arc-review|"
            "Character arc review|"
            "character_history,planned_scenes,story_theme|"
            "arc_findings,scene_adjustments|"
            "Review a fictional character's choices and changes for causal coherence across supplied scenes.|"
            "Findings reference actual scenes;Proposed changes preserve established facts;Theme is expressed through character decisions"
        ),
        (
            "worldbuilding-register|"
            "Worldbuilding consistency register|"
            "world_rules,story_excerpts,known_exceptions|"
            "canon_register,consistency_questions|"
            "Organize supplied fictional-world rules and identify contradictions without silently resolving canon.|"
            "Rules trace to supplied material;Exceptions remain explicit;Conflicts are questions for the author"
        ),
        (
            "songwriting-brief|"
            "Songwriting brief|"
            "song_theme,original_lyrics,arrangement_constraints|"
            "lyric_directions,arrangement_notes|"
            "Draft original songwriting directions grounded in supplied lyrics and emotional intent.|"
            "Directions preserve the intended theme;No third-party lyrics are copied;Arrangement follows supplied constraints"
        ),
        (
            "song-structure-review|"
            "Song structure review|"
            "original_song_sections,emotional_arc,performance_constraints|"
            "structure_findings,revision_options|"
            "Assess the supplied original song's pacing and propose distinct structure revisions.|"
            "Findings refer to actual sections;Revisions support the emotional arc;Performance constraints are respected"
        ),
        (
            "music-release-plan|"
            "Personal music release plan|"
            "release_facts,owned_assets,approved_schedule|"
            "release_tasks,asset_gaps|"
            "Plan a personal music release from confirmed facts and owned assets while retaining approval gates.|"
            "Tasks follow approved release dates;Missing rights or assets are flagged;No distribution or posting is executed"
        ),
        (
            "audio-session-notes|"
            "Audio session planning notes|"
            "session_goals,available_equipment,production_notes|"
            "session_steps,review_checks|"
            "Draft a feasible recording or mixing session sequence using actual equipment and supplied observations.|"
            "Steps use available equipment;Listening judgments remain tied to supplied notes;No unperformed audio analysis is claimed"
        ),
        (
            "artist-bio-draft|"
            "Artist biography draft|"
            "approved_biography,music_description,publication_context|"
            "bio_variants,fact_checks|"
            "Draft concise artist biographies from approved personal facts and original music description.|"
            "Facts remain faithful to the supplied biography;Variants fit their publication contexts;No invented credit or achievement"
        ),
        (
            "personal-research-note|"
            "Personal research note|"
            "research_question,source_excerpts,knowledge_context|"
            "research_note,open_questions|"
            "Synthesize supplied research into a useful personal note with explicit provenance.|"
            "Claims map to supplied excerpts;Uncertainty and disagreements remain visible;Original notes are not overwritten"
        ),
        (
            "reading-synthesis|"
            "Reading synthesis|"
            "reading_excerpts,learning_question,prior_notes|"
            "key_connections,followup_questions|"
            "Connect supplied readings to a personal learning question without reproducing entire copyrighted texts.|"
            "Connections cite supplied excerpts;The learning question stays central;Unknown conclusions remain questions"
        ),
        (
            "learning-plan|"
            "Personal learning plan|"
            "learning_goal,current_skills,available_time|"
            "learning_sessions,progress_checks|"
            "Draft a realistic learning sequence with observable progress checks and available time limits.|"
            "Sessions match current skills;Time limits are respected;Progress checks measure actual ability"
        ),
        (
            "personal-project-roadmap|"
            "Personal project roadmap|"
            "project_objective,existing_work,available_resources|"
            "project_milestones,dependency_questions|"
            "Plan a personal creative or technical project using existing work and realistic resource dependencies.|"
            "Milestones advance the supplied objective;Dependencies are explicit;Dates are not invented"
        ),
        (
            "repository-patch-brief|"
            "Personal repository patch brief|"
            "source_excerpt,desired_behavior,repository_constraints|"
            "patch_plan,regression_checks|"
            "Draft a concrete code-change plan from supplied source without scanning unrelated local repositories.|"
            "The plan refers to supplied source;Tests cover the desired behavior;No unexecuted patch is claimed as installed"
        ),
        (
            "local-tool-integration-plan|"
            "Local tool integration plan|"
            "tool_contracts,workbench_goal,privacy_constraints|"
            "integration_steps,validation_gates|"
            "Plan a local tool integration that preserves explicit inputs and privacy boundaries.|"
            "Contracts follow supplied tool documentation;Secrets remain outside prompts and outputs;No protected filesystem scan is implied"
        ),
        (
            "personal-admin-draft|"
            "Personal administration draft|"
            "admin_task,verified_records,required_format|"
            "admin_copy,missing_records|"
            "Draft a personal administrative document from explicitly supplied records without submitting or sending it.|"
            "Draft uses only supplied records;Required format is preserved;Unverified details remain gaps"
        ),
        (
            "personal-schedule-plan|"
            "Personal schedule plan|"
            "commitments,available_windows,priority_constraints|"
            "schedule_blocks,conflict_notes|"
            "Arrange supplied commitments into a feasible personal schedule without changing external calendars.|"
            "Blocks fit available windows;Conflicts remain explicit;No calendar update is executed"
        ),
        (
            "creative-feedback-synthesis|"
            "Creative feedback synthesis|"
            "feedback_notes,creative_intent,revision_limits|"
            "feedback_themes,revision_priorities|"
            "Synthesize supplied feedback into useful revision priorities while preserving the creator's intent.|"
            "Themes trace to actual feedback;Priorities respect revision limits;Conflicting feedback remains distinguishable"
        ),
        (
            "workbench-run-retrospective|"
            "Personal workbench run retrospective|"
            "run_receipts,accepted_outputs,observed_failures|"
            "run_lessons,next_experiments|"
            "Review actual personal-workbench receipts and accepted artifacts to propose bounded improvements.|"
            "Lessons cite supplied receipts;Useful output is separate from process success;Missing billing and metrics remain unavailable"
        ),
    ]
)
