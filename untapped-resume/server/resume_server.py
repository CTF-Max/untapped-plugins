"""Untapped Resume: local evidence-backed application materials over MCP stdio."""
import sys

sys.dont_write_bytecode = True

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_stdio import ToolError, serve
from evidence import scan_evidence
from job import read_job
from docx_writer import render_resume
from portfolio import render_portfolio
from ats import ats_check

VERSION = "0.1.0"
SOURCE = {"type": "object", "required": ["source_path", "quote"], "additionalProperties": False,
          "properties": {"source_path": {"type": "string", "minLength": 1},
                         "quote": {"type": "string", "minLength": 1}}}
LINE = {"type": "object", "required": ["text", "source"], "additionalProperties": False,
        "properties": {"text": {"type": "string", "minLength": 1}, "source": SOURCE, "bullet": {"type": "boolean"}}}
LINE_ARRAY = {"type": "array", "items": LINE}
RESUME = {"type": "object", "required": ["name", "sections"], "additionalProperties": False,
          "properties": {"name": LINE, "contact": LINE_ARRAY, "sections": {"type": "object",
                         "additionalProperties": False, "properties": {
                             name: LINE_ARRAY for name in ("Summary", "Experience", "Projects", "Education", "Skills", "Certifications")}}}}
PORTFOLIO = {"type": "object", "required": ["name", "projects"], "additionalProperties": False,
             "properties": {"name": LINE, "intro": LINE, "projects": {"type": "array", "minItems": 1,
                            "maxItems": 50, "items": {"type": "object", "required": ["title", "bullets", "fit_score"],
                            "additionalProperties": False, "properties": {"title": LINE, "bullets": LINE_ARRAY,
                            "fit_score": {"type": "number", "minimum": 0, "maximum": 100}, "fit_reason": LINE}}}}}


def tool(name, description, properties, required, readonly=True):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
            "annotations": {"readOnlyHint": readonly, "destructiveHint": not readonly,
                            "openWorldHint": name == "read_job"}}


TOOLS = [
    tool("scan_evidence", "Read local documents, project folders, git history and LinkedIn export ZIPs into source-linked evidence.",
         {"folder": {"type": "string"}, "max_files": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 500}}, ["folder"]),
    tool("read_job", "Parse one pasted job posting or fetch a user-provided HTTPS posting. The agent refines the literal requirements.",
         {"text": {"type": "string"}, "url": {"type": "string"}}, []),
    tool("render_resume", "Write a source-backed ATS-safe resume and sources.json. Existing output names are replaced; warns past one page.",
         {"resume_json": RESUME, "formats": {"type": "array", "items": {"enum": ["docx", "pdf", "txt"]},
          "default": ["docx", "pdf", "txt"]}, "out_dir": {"type": "string"}}, ["resume_json", "out_dir"], False),
    tool("render_portfolio", "Write self-contained index.html with the three highest-fit evidenced projects first and a source sidecar.",
         {"portfolio_json": PORTFOLIO, "out_dir": {"type": "string"}}, ["portfolio_json", "out_dir"], False),
    tool("ats_check", "Extract PDF text, check quoted sources and must-have coverage, and flag trace, hidden-text, layout and length issues.",
         {"pdf_path": {"type": "string"}, "job_json": {"type": "object"}, "sources_path": {"type": "string"}},
         ["pdf_path", "job_json", "sources_path"]),
]
TOOLS[1]["inputSchema"]["oneOf"] = [{"required": ["text"]}, {"required": ["url"]}]
FUNCTIONS = {function.__name__: function for function in (scan_evidence, read_job, render_resume, render_portfolio, ats_check)}


def call(name, args):
    if name not in FUNCTIONS:
        raise ToolError("Unknown tool: " + str(name)[:60])
    schema = next(t["inputSchema"] for t in TOOLS if t["name"] == name)
    if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
        raise ToolError("Missing or unknown arguments for " + name)
    try:
        return FUNCTIONS[name](**args)
    except (ValueError, TypeError, OSError) as exc:
        raise ToolError(str(exc)) from None


if __name__ == "__main__":
    serve(TOOLS, call, name="untapped-resume", version=VERSION)
