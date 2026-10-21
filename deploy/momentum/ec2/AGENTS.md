# EC2 deployment

The optional Brain adapter (`brain_readonly_adapter.py`) can serve a read-only
private snapshot with four tools and `sourceObservedAt`. Its cache and unchanged
renderer stay outside Git; never call the Brain collector, auto-refreshing load,
capture or search from snapshot mode. See the EC2 README.
