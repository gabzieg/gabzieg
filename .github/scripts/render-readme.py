"""Render profile sections with GitHub queries and bounded retries.

Inspired by ChrisTitusTech/ChrisTitusTech: replaces comment markers in README.gtpl
literally so repository descriptions are never executed as template code.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner url description isPrivate }
        contributions(last: 1) { nodes { occurredAt } }
      }
    }
  }
}
"""


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
                raise ValueError(f"GitHub returned GraphQL errors: {data['errors']}")
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


def recent_contributions(entries, login):
    filtered = [
        entry
        for entry in entries
        if not entry["repository"]["isPrivate"]
        and entry["repository"]["nameWithOwner"].lower() != f"{login}/{login}".lower()
        and entry["repository"]["nameWithOwner"].lower() != f"{login}/introduction".lower()
        and entry["contributions"]["nodes"]
    ]
    filtered.sort(
        key=lambda entry: entry["contributions"]["nodes"][0]["occurredAt"],
        reverse=True,
    )
    return [
        repo_line(
            entry["repository"]["nameWithOwner"],
            entry["repository"]["url"],
            entry["repository"]["description"],
        )
        for entry in filtered[:5]
    ]


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
    data = api(["graphql", "-f", f"query={QUERY}", "-f", f"login={login}"])
    entries = data["data"]["user"]["contributionsCollection"]["commitContributionsByRepository"]
    result = {"RECENT_CONTRIBUTIONS": recent_contributions(entries, login)}

    repos = []
    page = 1
    while len(repos) < 5:
        batch = api([f"users/{login}/repos?sort=pushed&direction=desc&per_page=100&page={page}"])
        repos.extend(
            repo
            for repo in batch
            if not repo["fork"]
            and not repo["private"]
            and repo["full_name"].lower() != f"{login}/{login}".lower()
            and repo["full_name"].lower() != f"{login}/introduction".lower()
        )
        if len(batch) < 100:
            break
        page += 1

    result["RECENT_REPOS"] = [
        repo_line(repo["full_name"], repo["html_url"], repo["description"])
        for repo in repos[:5]
    ]

    stars = api([f"users/{login}/starred?sort=created&direction=desc&per_page=5"])
    star_lines = [
        repo_line(repo["full_name"], repo["html_url"], repo["description"])
        for repo in stars
        if not repo.get("private")
    ]
    result["RECENT_STARS"] = star_lines if star_lines else ["- Exploring open-source projects across AI, Kotlin, and Developer Tooling."]
    return result


if __name__ == "__main__":
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "gabzieg")
    template_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    template_text = template_path.read_text(encoding="utf-8")
    output_path.write_text(render(template_text, sections(owner)), encoding="utf-8")
