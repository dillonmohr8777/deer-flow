# Uploads storage details and view_image injection

Moved verbatim out of `backend/AGENTS.md` to keep the AGENTS.md chain under its byte budget. Nothing was dropped.

## Uploads

- Files stored in thread-isolated directories under the resolving user's bucket (`users/{user_id}/threads/{thread_id}/user-data/uploads`). For IM channels the owner is threaded explicitly via the `user_id=` kwarg (see IM Channels → Owner-scoped file storage); HTTP/embedded callers resolve it from `get_effective_user_id()`
- Duplicate filenames within one request get `_N` suffixes to prevent overwrites.
- Gateway HTTP uploads stage bytes as `.upload-*.part` files and atomically replace the destination only after size validation. These staging files are hidden from upload listings, agent upload context, and sandbox listing/search tools, and swept on Gateway startup if a hard crash leaves one behind.
- Gateway HTTP upload/list/delete handlers offload filesystem work through `deerflow.utils.file_io.run_file_io`, a dedicated ContextVar-preserving file IO executor. Non-mounted sandbox uploads acquire sandboxes with `SandboxProvider.acquire_async()` and offload `read_bytes()` plus `sandbox.update_file()` together.
- Mounted uploads skip sandbox acquire/sync. AIO remote/provisioner requires accurate `sandbox.thread_data_mounts: true`; omission keeps backend auto-detection.
- `UploadsMiddleware` caps outline titles at 200 characters and previews at 2000 including markers. Titles use `original_user_content`, not upload-prefixed content; attachment-only titles use a sanitized, bounded filename or count.

## view_image injection

- Images are converted to base64 and appended to the model request as a hidden message carrying both a reserved ID prefix and a server-owned metadata marker; Gateway strips that marker from untrusted input, and the middleware requires both identifiers to recognize its own message. The middleware injects inside `wrap_model_call`, so the payload never enters graph state: checkpoints retain only lightweight `viewed_images` metadata, while client-chosen IDs survive. It also sweeps its own message out of every request before rebuilding it, so a payload stranded in an older checkpoint by an interrupted run stops being resent
