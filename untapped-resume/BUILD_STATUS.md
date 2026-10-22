# Untapped Resume build checkpoint

Authority: `../CODEX_BRIEF_untapped-resume.md`, user request 2026-10-22.
Scope: free, local, stdlib Python 3.10+, five tools; no publishing or git staging.

Completed: all five tools, source-backed DOCX/PDF/TXT and portfolio writers, workflow
skill, documentation, MIT license, icon, offline fixtures/tests, both host manifests,
both marketplace registrations and vendored MCP transport. Nothing published or staged.

Verified 2026-10-22 with the user-specified Python 3.12 executable, from repo root:

- `python -m unittest discover -s plugins/untapped-resume/tests`: **Ran 29 tests in 1.116s — OK**.
- `python plugins/tools/sync_shared.py --check`: Shared copies current (5 plugin(s)).
- `python plugins/tools/manifests.py --check`: Manifests current (5 plugins).
- Skill-creator validator: `Skill is valid!`
- Independent Poppler `pdftotext` output matches generated TXT.
- Extracted MCPB runs a real tools/call from an isolated directory.
- All 56 recorded files in the four other plugin folders retain their original hashes.
- Independent skill scenario: refused invented Docker experience; directory flag
  removed internship option; preserved sourcing, length checks and kit deliverables.

Bundle: `../dist/untapped-resume-mcp-0.1.0.mcpb` (25,822 bytes).
SHA-256: `f1bfac38c123c3b66e5513a09dbb04ad31da27f96f4ffe9c82d18c9bd5ceed72`.
Registry metadata: `../registry/untapped-resume.server.json`.
Local verification outputs and protection hashes are in ignored `.build/`.

Pending external check: `claude plugin validate --strict plugins/untapped-resume`.
The `claude` CLI was unavailable in this sandbox, so it was skipped per the user.

Implementation adjustments and limitations:

- Besides registration, the shared MCPB builder needed plugin-name selection: it
  previously ignored the brief's positional name and rebuilt every bundle. Added
  that filter and an empty-settings registration, preserving existing plugin data.
- PDF output uses standard Windows-1252 fonts. Other scripts explicitly fail PDF
  generation without changing spelling; DOCX/TXT remain available for external
  Unicode PDF export. General PDF extraction and graphics checks are best effort.
- Git fixture commits are created offline in isolated test folders using a checked-in
  deterministic fast-import fixture, with no git add/commit commands on this repo.
- Python's restricted-permission temporary directories failed in this Windows sandbox.
  Tests now use isolated inherited-permission directories and pass. Automatic approval
  review rejected deletion of the initial empty scratch directories as “blocked by
  policy”; they remain ignored under `.test-tmp/` and are not in the bundle.

Next action: Claude runs the strict validator. Publishing remains outside this build.
