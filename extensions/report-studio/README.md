# Report Studio

An extension that lets agents render a client's weekly report page, then propose deploying it through the approvals inbox. Only after a human approves does one client's page publish to Netlify.

## Pieces

- Tool `build_report_page(client_id, week, sections, client_name="")` renders `reports/<client_id>/index.html` plus the client's existing logo (`<assets_dir>/<client_id>.<ext>`) into `<staging_dir>/<client_id>/<week>/`. It uses only the data passed in, never generates a logo, and never deploys. It returns a `bundle_sha256` of the staged files.
- Approval type `deploy_report` (target = client id, payload = `{week, bundle_sha256}`), filed with the normal `propose_action` tool. The adapter refuses if the staged files no longer match `bundle_sha256`, so a page edited after proposal never ships under an old approval.
- Core seam: `deerflow.approvals.register_action_type` and `app.gateway.approval_adapters.register_adapter`. Extension types live in separate registries from the built-in ones. Exactly-once and approve-before-run come from the existing compare-and-set in the approvals router.

## One-client deploy

Netlify deploys are whole-site snapshots. The adapter reads the live file list (`GET /sites/{id}/files`), builds a manifest that equals live except for this client's page and logo, creates the deploy, and uploads only the files Netlify asks for. This gives the same result as copying every other client's live `index.html` back before deploying. It refuses to run when:

- a staged file is anything other than `/reports/<client_id>/index.html` or `/assets/*`;
- a staged asset already exists live with different content;
- the live listing is empty.

After the deploy is ready it lists the files again and fails if any path other than the client's own changed by sha, then requires `GET <site_url>/reports/<client_id>/` to return 200. A failure after publish is reported as a failed approval, and the message says the deploy may already be live.

## Enable

1. Install (from `backend/`): `make extension-install SOURCE=/abs/path/to/deer-flow/extensions/report-studio`, or `uv run deerflow extensions install /abs/path/to/extensions/report-studio`. Turn it on or off with `deerflow extensions enable report-studio` and `deerflow extensions disable report-studio`. Restart the Gateway after any change.
2. Private plugin config, under the managed `plugins:` record in `config.yaml`:

   ```yaml
   config:
     staging_dir: /path/to/report-staging
     assets_dir: /path/to/client-logos   # <client_id>.png|svg|webp|jpg
     site_id: <netlify site id>
     site_url: https://<site>.netlify.app
   ```

3. Load the tool in the top-level `tools:` list of `config.yaml`:

   ```yaml
   - name: build_report_page
     group: web
     use: deerflow_report_studio.render:build_report_page
   ```

4. Set `NETLIFY_AUTH_TOKEN` in the Gateway environment. It is read at execution time only and is never stored, logged or returned. If it is missing, the approval fails with a clear message and nothing deploys. `token_env` in the plugin config renames the variable.

## Tests

`backend/tests/test_report_studio.py` (11 tests, no network, fake Netlify): render, one-client isolation, approval gating and exactly-once.
