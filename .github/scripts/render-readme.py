"""Render profile sections with GitHub queries and bounded retries.

Replaces comment markers in README.gtpl literally and deduplicates against
highlighted repositories so no project appears twice on the profile.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


HIGHLIGHTED_REPOS = {
    "atmosfera",
    "subtrack",
    "bropilot",
    "ai-usage-menu",
    "readafter",
}

IGNORED_REPOS = {
    "gabzieg",
    "introduction",
}


def api(arguments):
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["gh", "api", *arguments],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            data = json.loads(result.stdout)
            if isinstance(data, dict) and data.get("errors"):
                raise ValueError(f"GitHub returned errors: {data['errors']}")
            return data
        except (subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
            if attempt == 2:
                raise RuntimeError(f"GitHub query failed after 3 attempts: {exc}") from None
            print("GitHub query failed; retrying...", file=sys.stderr)
            time.sleep(3 * (attempt + 1))


def clean(value):
    text = " ".join((value or "").splitlines()).strip()
    return text if text else "Active repository."


def repo_line(name, url, description):
    return f"- [{name}]({url}) - {clean(description)}"


def render(template, sections_map):
    for name in sections_map:
        marker = "{{ /* " + name + " */ }}"
        if template.count(marker) != 1:
            raise ValueError(f"Expected exactly one {name} marker")
    return re.sub(
        r"\{\{ /\* (RECENT_[A-Z_]+) \*/ \}\}",
        lambda match: "\n" + "\n".join(sections_map[match.group(1)]),
        template,
    )


def sections(login):
    repos = []
    page = 1
    while len(repos) < 12:
        batch = api([f"users/{login}/repos?sort=pushed&direction=desc&per_page=100&page={page}"])
        repos.extend(
            repo
            for repo in batch
            if not repo["fork"]
            and not repo["private"]
            and repo["name"].lower() not in IGNORED_REPOS
            and repo["name"].lower() not in HIGHLIGHTED_REPOS
        )
        if len(batch) < 100:
            break
        page += 1

    return {
        "RECENT_REPOS": [
            repo_line(repo["full_name"], repo["html_url"], repo["description"])
            for repo in repos[:8]
        ]
    }


if __name__ == "__main__":
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "gabzieg")
    template_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    template_text = template_path.read_text(encoding="utf-8")
    output_path.write_text(render(template_text, sections(owner)), encoding="utf-8")
