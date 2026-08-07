# Package instructions

- Keep this package independent from `src/amra` and other legacy AMRA modules.
- Use Python standard-library dependencies unless the user explicitly approves another dependency.
- Treat `campaigns/` as mutable research state and every other directory as package infrastructure.
- Use `apply_patch` for edits and run both skill validation and package tests after changes.
- Never weaken a closure contract or phase gate merely to advance a campaign.
