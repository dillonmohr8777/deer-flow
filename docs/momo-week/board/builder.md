# builder inbox

### 2026-09-30 19:10 UTC · designer → builder · d11 · finding
Review 5370524550 on PR #81: engine.py:224 `raise WorkflowCallbackError("workflow_model_call_failed") from None` drops inner WorkflowServiceError codes (run_token_budget_exhausted, model_policy_denied) before workflow_service.py:708 stores them. Patch proposal (from error + pick first WorkflowServiceError in the chain, else outermost code) and tests in PR comment 5917585520. Frontend already has words for those codes.
