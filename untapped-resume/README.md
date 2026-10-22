# Untapped Resume

Build a resume, portfolio and LinkedIn kit for one job using evidence you already have.
Tailored, never invented: missing qualifications stay **no evidence yet** and go into a practical gap plan.

Free, local, Python 3.10 or newer, standard library only. No account, licence key, monthly quota or payment.
The plugin cannot post to LinkedIn; paste + upload takes about 2 minutes. It does not guarantee interviews.

## Install and use

Install `untapped-resume` from the Untapped Plugins marketplace in Codex or Claude Code once released.
Both host manifests and the shared `tailor-resume` skill are included. Python must be on the host's PATH.
The MCPB contains the five tools; plugin installation also includes the guided skill.

For a standalone local MCP configuration, run `python` with the absolute path to `server/resume_server.py`
as its argument. No environment variables or credentials are required. The server speaks JSON-RPC on stdio;
do not launch it as a web server. You can try: “Tailor my resume to this job using this project folder.”

Give the agent one job posting, a folder of selected evidence, and an output folder for this job.
Supported evidence includes Markdown, text, README files, DOCX, best-effort PDF text, git metadata and
LinkedIn export ZIPs containing Positions, Education, Skills, Certifications or Projects CSV files.
No repository code is executed. Commit metadata does not prove the applicant's contribution or proficiency.

| Tool | Result |
|---|---|
| `scan_evidence(folder, max_files=500)` | Source-linked excerpts, explicit dates and reader notes |
| `read_job(text=...)` or `read_job(url=...)` | Stated title/company, must-haves, nice-to-haves and employer terms |
| `render_resume(resume_json, out_dir, formats=["docx","pdf","txt"])` | Resume files and private `sources.json` |
| `render_portfolio(portfolio_json, out_dir)` | Self-contained `index.html` and private source map |
| `ats_check(pdf_path, job_json, sources_path)` | Extracted text, coverage and provenance/layout flags |

Only `read_job` can access the network, to fetch the HTTPS posting you supply (20-second request timeout).
The other tools operate on local files. The skill guides the agent to write the LinkedIn kit, cover letter,
match table and a 1–4 week gap plan locally. See [the workflow and JSON contracts](skills/tailor-resume/SKILL.md).
Directory workflows set `directory_build=true`, which disables the optional internship suggestion.

## Source-backed output

Every factual input line has this shape:

```json
{
  "text": "Built a Python inventory tool.",
  "source": {
    "source_path": "/absolute/path/project/README.md",
    "quote": "Built a Python inventory tool."
  }
}
```

`resume_json` contains a sourced `name`, optional sourced `contact` array and a `sections` object.
Section keys are Summary, Experience, Projects, Education, Skills and Certifications; each holds an array
of sourced lines. Experience and Projects default to bullets; set `bullet:false` for a role/date label.
The renderer refuses missing sources on any factual line, not just bullets. The source map records wrapped
lines and output hashes. The checker reads sources again and flags missing quotes and unsupported words.
A citation is not proof: the agent must still check attribution, meaning, dates, metrics and ownership.

`portfolio_json` has sourced `name`, optional sourced `intro`, and `projects`. Each project has a sourced
`title`, sourced `bullets`, a numeric `fit_score` from 0–100, and optional sourced `fit_reason`.
The three highest scores lead, with fewer if there are fewer evidenced projects. The score is supplied by
the agent for ordering. The HTML has no scripts, linked resources or branding footer. Upload only the
reviewed `index.html` to GitHub Pages or Cloudflare Pages; keep source maps and local paths private.

## Limits that stay visible

- Resume files use a single column, standard Courier fonts and real text. More than one page triggers a
  warning; content is not silently removed. DOCX pagination can vary with the viewer's font metrics.
- Built-in PDF output supports Windows-1252 text, including common Western accents. For other scripts it
  refuses PDF output without replacing characters; use DOCX/TXT and export from Word or LibreOffice.
- General PDF reading is best effort: no OCR, encrypted text or custom font-map support. Hidden text,
  images and tagged tables are flagged when detected; arbitrary graphics and untagged tables require review.
- Coverage uses literal terms found in both the resume and quoted local evidence, not a hiring prediction.
  Paraphrases may need manual review. Missing input, unknown ownership or an unreadable source is not proof.
- Input reads are bounded. Large documents/archives and unsupported files may be skipped with notes.
  Keep job evidence in a small dedicated folder. The scanner never substitutes file times for stated dates.
- Output files have fixed names and are replaced in the chosen directory. Use a separate directory per job.

## Development checks

From the repository root:

```text
python -m unittest discover -s plugins/untapped-resume/tests
python plugins/tools/sync_shared.py --check
python plugins/tools/manifests.py --check
claude plugin validate --strict plugins/untapped-resume
python plugins/tools/build_mcpb.py untapped-resume
```

Tests use local fixtures and an injected job-page transport; they make no network requests.
The vendored MCP transport comes from `plugins/shared/mcp_stdio.py` via `plugins/tools/sync_shared.py`.

By **Find Untapped Growth** · [Homepage](https://finduntappedgrowth.com/) · [MIT licence](LICENSE) · [Privacy](PRIVACY.md)
