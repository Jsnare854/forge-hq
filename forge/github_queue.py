"""The approval queue lives in GitHub Issues: one issue per draft, approve with the `approved` label."""
from __future__ import annotations

import os

import requests

LABELS = {
    "draft": ("c5a23a", "Waiting for your approval"),
    "approved": ("2ea043", "Approved: publish to Printify + Etsy"),
    "published": ("1f6feb", "Live on Etsy via Printify"),
    "risk-high": ("d73a4a", "Possible trademark problem, review carefully"),
    "override-risk": ("8250df", "Publish even though flagged high risk"),
    "publish-failed": ("b60205", "Publishing hit an error; see the comment"),
}


class GitHub:
    def __init__(self, token: str | None = None, repo: str | None = None, session: requests.Session | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        if not self.token or not self.repo:
            raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY must be set (they are automatic inside GitHub Actions).")
        self.http = session or requests.Session()
        self.owner = self.repo.split("/")[0]

    def _req(self, method, path, **kw):
        r = self.http.request(
            method,
            f"https://api.github.com/repos/{self.repo}{path}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            timeout=30,
            **kw,
        )
        if r.status_code >= 400 and not (method == "POST" and path == "/labels" and r.status_code == 422):
            raise RuntimeError(f"GitHub {method} {path} failed ({r.status_code}): {r.text[:300]}")
        return r.json() if r.content else {}

    def ensure_labels(self):
        for name, (color, desc) in LABELS.items():
            self._req("POST", "/labels", json={"name": name, "color": color, "description": desc})

    def create_issue(self, title, body, labels):
        return self._req("POST", "/issues", json={"title": title, "body": body, "labels": labels})

    def issue(self, number):
        return self._req("GET", f"/issues/{number}")

    def comment(self, number, text):
        return self._req("POST", f"/issues/{number}/comments", json={"body": text})

    def add_labels(self, number, labels):
        return self._req("POST", f"/issues/{number}/labels", json={"labels": labels})

    def remove_label(self, number, label):
        try:
            self._req("DELETE", f"/issues/{number}/labels/{label}")
        except RuntimeError:
            pass

    def close(self, number):
        return self._req("PATCH", f"/issues/{number}", json={"state": "closed"})

    def raw_url(self, path: str, branch: str = "main") -> str:
        return f"https://github.com/{self.repo}/blob/{branch}/{path}?raw=true"
