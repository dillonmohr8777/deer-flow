# Native iOS shell

The actual device-authentication controller lives in `MomoMobileCore`, shared
by the App target and the Swift package tests. Its one current state is locked,
authenticating, or unlocked. Only the current attempt may settle; `lock()`
retires ownership before invalidating the system context. Keep late success/error
and newer-attempt coverage with a controlled authentication dependency.

Run the package suite and the available App build checks described in README.md.
Package tests do not establish physical-device or signed iOS app acceptance.
Generate Xcode projects from project.yml; do not hand-edit generated projects.
