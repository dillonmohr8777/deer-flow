# EC2 deployment

The optional Brain adapter (`brain_readonly_adapter.py`) can serve a read-only
private snapshot with four tools and `sourceObservedAt`. Its cache and unchanged
renderer stay outside Git; never call the Brain collector, auto-refreshing load,
capture or search from snapshot mode. See the EC2 README.

`Dockerfile.memory-profile` is a two-file overlay of reviewed PR198 onto a verified
live gateway base. Export only the pinned source files into its build context.
Do not replace the base with latest main or infer a global model-policy change.
