"""Self-contained accessible HTML; no resources, links, tracking, or publishing."""
import json
import math
from html import escape
from pathlib import Path

from docx_writer import sourced


def render_portfolio(portfolio_json, out_dir):
    if not isinstance(portfolio_json, dict) or set(portfolio_json) - {"name", "intro", "projects"}:
        raise ValueError("portfolio_json takes name, optional intro, and projects.")
    rows = []

    def line(item):
        text, source = sourced(item)
        rows.append({"text": text, "source": source})
        return escape(text)

    name = line(portfolio_json.get("name"))
    intro = line(portfolio_json["intro"]) if portfolio_json.get("intro") else ""
    projects = portfolio_json.get("projects")
    if not isinstance(projects, list) or not projects or len(projects) > 50:
        raise ValueError("projects must contain 1 to 50 evidence-backed projects.")
    for project in projects:
        if not isinstance(project, dict) or set(project) - {"title", "bullets", "fit_score", "fit_reason"}:
            raise ValueError("Each project takes title, bullets, fit_score, and optional fit_reason.")
        score = project.get("fit_score")
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError("Each project needs an agent-assessed fit_score from 0 to 100.")
        if not isinstance(project.get("bullets"), list) or not project["bullets"]:
            raise ValueError("Each project needs evidence-backed bullets.")
    cards = []
    for i, project in enumerate(sorted(projects, key=lambda p: -p["fit_score"])):
        title = line(project.get("title"))
        bullets = "".join(f"<li>{line(item)}</li>" for item in project["bullets"])
        reason = f'<p>{line(project["fit_reason"])}</p>' if project.get("fit_reason") else ""
        if i == 3:
            cards.append('<h2>More projects</h2>')
        cards.append(f'<article aria-labelledby="project-{i}"><h3 id="project-{i}">{title}</h3>'
                     f'{reason}<ul>{bullets}</ul></article>')
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>{name} | Portfolio</title>
<style>
:root {{color-scheme: light; font: 1.05rem/1.65 system-ui, sans-serif; color: #172b31; background: #f4f8f7;}}
body {{margin: 0;}} main {{max-width: 54rem; margin: auto; padding: 2rem 1rem; overflow-wrap: anywhere;}}
header {{border-bottom: .25rem solid #0f766e; margin-bottom: 2rem;}}
h1,h2,h3 {{line-height: 1.25;}} h1 {{font-size: clamp(2rem, 7vw, 3rem);}}
article {{background: white; border: 1px solid #b6cdc8; border-radius: .6rem; padding: 1rem 1.4rem; margin: 1rem 0;}}
li {{margin: .5rem 0;}} @media print {{body {{background: white;}} article {{break-inside: avoid;}}}}
</style></head><body><main><header><h1>{name}</h1><p>{intro}</p></header>
<section aria-labelledby="selected"><h2 id="selected">Selected projects</h2>{''.join(cards)}</section>
</main></body></html>
'''
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(html, encoding="utf-8")
    sidecar = out / "portfolio-sources.json"
    sidecar.write_text(json.dumps({"lines": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "sources_path": str(sidecar), "projects": len(projects),
            "featured": min(3, len(projects)), "warnings": [] if len(projects) >= 3 else
            ["Fewer than three evidenced projects were supplied; no projects were invented."]}
