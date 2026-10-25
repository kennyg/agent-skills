#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
harden.py — audit public GitHub repos against a security baseline, and apply it.

    harden.py [REPO ...] [--owner LOGIN] [--json]          # audit (default)
    harden.py [REPO ...] [--owner LOGIN] --plan            # audit, then list the changes
    harden.py [REPO ...] [--owner LOGIN] --apply [--yes]   # list the changes, then make them

With no REPO, the scope is every public repo of --owner, else of the gh login.
Forks and archived repos are skipped unless --include-forks / --include-archived.
Every request goes through `gh api` with a list of arguments, never a shell string.
The script prints values and HTTP messages only, never headers or tokens.

Exit status: 0 when every repo meets the baseline (audit) or every change held
(apply), 1 when a repo misses it or a change failed, 2 on a usage or gh error.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

DEFAULT_JOBS = 6
RETRIES = 3
# Longest wait for a rate limit to reset before the request counts as failed.
MAX_WAIT = 300
INSIDE_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
LINTERS_RE = re.compile(r"\b(actionlint|zizmor)\b")
ADMIN_BYPASS = {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}

RULESETS = {
    "ruleset_main": {
        "name": "Protect main",
        "target": "branch",
        "include": "~DEFAULT_BRANCH",
        "rules": ("deletion", "non_fast_forward"),
        "bypass": None,
    },
    "ruleset_tags": {
        "name": "Protect release tags",
        "target": "tag",
        "include": "refs/tags/v*",
        "rules": ("creation", "update", "deletion", "non_fast_forward"),
        "bypass": ADMIN_BYPASS,
    },
}


class GhError(Exception):
    """gh is not installed."""


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    data: object
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def message(self) -> str:
        if isinstance(self.data, dict) and self.data.get("message"):
            return str(self.data["message"])
        return f"HTTP {self.status}"


def parse_response(stdout: str) -> Response:
    """Split `gh api --include` output into status, headers and JSON body."""
    text = stdout.replace("\r\n", "\n")
    head, _, body = text.partition("\n\n")
    lines = head.split("\n")
    match = re.match(r"HTTP/[\d.]+ (\d{3})", lines[0] if lines else "")
    if not match:
        return Response(0, {}, None, text)
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    body = body.strip()
    try:
        data = json.loads(body) if body else None
    except json.JSONDecodeError:
        data = None
    return Response(int(match.group(1)), headers, data, body)


def rate_limit_wait(resp: Response, now: float) -> float | None:
    """Seconds to wait before a retry, or None when the response is not a rate limit."""
    if resp.status not in (403, 429):
        return None
    if resp.headers.get("retry-after", "").isdigit():
        return float(resp.headers["retry-after"])
    if resp.headers.get("x-ratelimit-remaining") == "0" and resp.headers.get("x-ratelimit-reset", "").isdigit():
        return max(1.0, float(resp.headers["x-ratelimit-reset"]) - now + 1)
    if "rate limit" in resp.message.lower():
        return 60.0
    return None


class Gh:
    """Thin wrapper over `gh api`. `run` and `sleep` are injectable for tests."""

    def __init__(self, run=subprocess.run, sleep=time.sleep, clock=time.time, max_wait: float = MAX_WAIT):
        self._run = run
        self._sleep = sleep
        self._clock = clock
        self.max_wait = max_wait

    def call(self, method: str, path: str, body: object | None = None, graphql: dict | None = None) -> Response:
        argv = ["gh", "api", "--include", "--method", method, path]
        if graphql is not None:
            for key, value in graphql.items():
                argv += ["-f", f"{key}={value}"]
        stdin = None
        if body is not None:
            argv += ["--input", "-"]
            stdin = json.dumps(body)
        for attempt in range(RETRIES + 1):
            try:
                proc = self._run(argv, input=stdin, capture_output=True, text=True, check=False)
            except FileNotFoundError as exc:
                raise GhError("gh is not installed") from exc
            resp = parse_response(proc.stdout)
            if resp.status == 0:
                # No HTTP response: a network error, or gh is not logged in. Retry, then report it.
                # A POST may have reached GitHub before the reply was lost, and a second one would
                # create a second resource, so only idempotent requests are sent again.
                lines = (proc.stderr or "").strip().splitlines()
                resp.data = {"message": lines[-1] if lines else "gh api returned no HTTP response"}
                if attempt < RETRIES and (method != "POST" or path == "graphql"):
                    self._sleep(2**attempt)
                    continue
                return resp
            wait = rate_limit_wait(resp, self._clock())
            if wait is None or attempt == RETRIES or wait > self.max_wait:
                return resp
            self._sleep(wait)
        return resp

    def get(self, path: str) -> Response:
        return self.call("GET", path)

    def pages(self, path: str, limit: int = 10) -> list:
        """GET a list endpoint page by page, 100 items a page, up to `limit` pages."""
        items: list = []
        sep = "&" if "?" in path else "?"
        for page in range(1, limit + 1):
            resp = self.get(f"{path}{sep}per_page=100&page={page}")
            if not resp.ok or not isinstance(resp.data, list):
                if page == 1:
                    raise ApiError(resp)
                break
            items.extend(resp.data)
            if len(resp.data) < 100:
                break
        return items


class ApiError(Exception):
    def __init__(self, resp: Response):
        super().__init__(resp.message)
        self.resp = resp


# --- Per-repo state ----------------------------------------------------------


@dataclass
class Repo:
    """Cached reads for one repo. `forget` drops them so a check can read again."""

    gh: Gh
    name: str
    _cache: dict = field(default_factory=dict)

    def cached(self, key: str, fetch: Callable[[], object]) -> object:
        if key not in self._cache:
            self._cache[key] = fetch()
        return self._cache[key]

    def forget(self) -> None:
        self._cache.clear()

    def info(self) -> dict:
        def fetch() -> dict:
            resp = self.gh.get(f"repos/{self.name}")
            if not resp.ok:
                raise ApiError(resp)
            return resp.data

        return self.cached("info", fetch)

    def endpoint(self, suffix: str) -> Response:
        return self.cached(f"GET {suffix}", lambda: self.gh.get(f"repos/{self.name}/{suffix}"))

    def rulesets(self) -> list[dict]:
        """Repo-level rulesets with full detail, so conditions and rules can be compared."""

        def fetch() -> list[dict]:
            resp = self.gh.get(f"repos/{self.name}/rulesets?includes_parents=false&per_page=100")
            if resp.status == 404:
                return []
            if not resp.ok:
                raise ApiError(resp)
            wanted = {spec["name"] for spec in RULESETS.values()}
            full = []
            for item in resp.data:
                if item.get("name") not in wanted:
                    continue
                detail = self.gh.get(f"repos/{self.name}/rulesets/{item['id']}")
                if not detail.ok:
                    raise ApiError(detail)
                full.append(detail.data)
            return full

        return self.cached("rulesets", fetch)


# --- Baseline checks ---------------------------------------------------------

NA = "n/a"


@dataclass
class State:
    value: str
    ok: bool | None  # None: the repo does not have the feature.


@dataclass
class Check:
    key: str
    column: str
    desired: str
    read: Callable[[Repo], State]
    apply: Callable[[Repo], Response]


def on_off(flag: object) -> str:
    return "on" if flag else "off"


def read_pr_policy(repo: Repo) -> State:
    value = repo.info().get("pull_request_creation_policy")
    if value is None:
        return State(NA, None)
    return State(value, value == "collaborators_only")


def apply_pr_policy(repo: Repo) -> Response:
    return repo.gh.call("PATCH", f"repos/{repo.name}", {"pull_request_creation_policy": "collaborators_only"})


def read_enabled_endpoint(suffix: str) -> Callable[[Repo], State]:
    def read(repo: Repo) -> State:
        resp = repo.endpoint(suffix)
        if resp.status == 404:
            return State(NA, None)
        if not resp.ok:
            raise ApiError(resp)
        enabled = bool(resp.data.get("enabled"))
        return State(on_off(enabled), enabled)

    return read


def put(suffix: str, body: object | None = None) -> Callable[[Repo], Response]:
    return lambda repo: repo.gh.call("PUT", f"repos/{repo.name}/{suffix}", body)


def read_fork_approval(repo: Repo) -> State:
    resp = repo.endpoint("actions/permissions/fork-pr-contributor-approval")
    if resp.status == 404:
        return State(NA, None)
    if not resp.ok:
        raise ApiError(resp)
    value = resp.data.get("approval_policy", NA)
    return State(value, value == "all_external_contributors")


def read_vuln_alerts(repo: Repo) -> State:
    # This endpoint answers 204 when alerts are on and 404 when they are off.
    resp = repo.endpoint("vulnerability-alerts")
    if resp.status == 204:
        return State("on", True)
    if resp.status == 404:
        return State("off", False)
    raise ApiError(resp)


def read_workflow_token(repo: Repo) -> State:
    resp = repo.endpoint("actions/permissions/workflow")
    if resp.status == 404:
        return State(NA, None)
    if not resp.ok:
        raise ApiError(resp)
    perms = resp.data.get("default_workflow_permissions", NA)
    approve = bool(resp.data.get("can_approve_pull_request_reviews"))
    value = f"{perms}{'+approve' if approve else ''}"
    return State(value, perms == "read" and not approve)


def read_security(feature: str) -> Callable[[Repo], State]:
    def read(repo: Repo) -> State:
        status = (repo.info().get("security_and_analysis") or {}).get(feature, {}).get("status")
        if status is None:
            return State(NA, None)
        return State(on_off(status == "enabled"), status == "enabled")

    return read


def apply_security(feature: str) -> Callable[[Repo], Response]:
    body = {"security_and_analysis": {feature: {"status": "enabled"}}}
    return lambda repo: repo.gh.call("PATCH", f"repos/{repo.name}", body)


def ruleset_gaps(ruleset: dict, spec: dict) -> list[str]:
    """Names of the parts of `ruleset` that fall short of `spec`. Empty means it meets it."""
    gaps = []
    if ruleset.get("target") != spec["target"]:
        gaps.append("target")
    if ruleset.get("enforcement") != "active":
        gaps.append("enforcement")
    ref = (ruleset.get("conditions") or {}).get("ref_name") or {}
    if spec["include"] not in (ref.get("include") or []) or spec["include"] in (ref.get("exclude") or []):
        gaps.append("refs")
    types = {rule.get("type") for rule in ruleset.get("rules") or []}
    if not set(spec["rules"]) <= types:
        gaps.append("rules")
    if spec["bypass"] and spec["bypass"] not in (ruleset.get("bypass_actors") or []):
        gaps.append("bypass")
    return gaps


def find_rulesets(repo: Repo, spec: dict) -> list[dict]:
    return [r for r in repo.rulesets() if r.get("name") == spec["name"]]


def read_ruleset(key: str) -> Callable[[Repo], State]:
    spec = RULESETS[key]

    def read(repo: Repo) -> State:
        found = find_rulesets(repo, spec)
        if not found:
            return State("missing", False)
        best = min((ruleset_gaps(r, spec) for r in found), key=len)
        value = "ok" if not best else "differs(" + ",".join(best) + ")"
        if len(found) > 1:
            value += f" x{len(found)}"
        return State(value, not best)

    return read


def ruleset_body(spec: dict, existing: dict | None) -> dict:
    """The ruleset to send: the spec on its own, or merged into what exists so nothing is lost."""
    existing = existing or {}
    ref = dict((existing.get("conditions") or {}).get("ref_name") or {})
    include = list(ref.get("include") or [])
    if spec["include"] not in include:
        include.append(spec["include"])
    exclude = [p for p in ref.get("exclude") or [] if p != spec["include"]]
    rules = list(existing.get("rules") or [])
    have = {rule.get("type") for rule in rules}
    rules += [{"type": t} for t in spec["rules"] if t not in have]
    bypass = list(existing.get("bypass_actors") or [])
    if spec["bypass"] and spec["bypass"] not in bypass:
        bypass.append(spec["bypass"])
    conditions = dict(existing.get("conditions") or {})
    conditions["ref_name"] = {"include": include, "exclude": exclude}
    return {
        "name": spec["name"],
        "target": spec["target"],
        "enforcement": "active",
        "conditions": conditions,
        "rules": rules,
        "bypass_actors": bypass,
    }


def apply_ruleset(key: str) -> Callable[[Repo], Response]:
    spec = RULESETS[key]

    def apply(repo: Repo) -> Response:
        # Update the ruleset of that name if one exists. Never create a second one.
        found = find_rulesets(repo, spec)
        if found:
            target = min(found, key=lambda r: len(ruleset_gaps(r, spec)))
            return repo.gh.call("PUT", f"repos/{repo.name}/rulesets/{target['id']}", ruleset_body(spec, target))
        return repo.gh.call("POST", f"repos/{repo.name}/rulesets", ruleset_body(spec, None))

    return apply


# Order matters for apply: vulnerability alerts before Dependabot security
# updates, and secret scanning before push protection.
CHECKS = [
    Check("pr_policy", "prs", "collaborators_only", read_pr_policy, apply_pr_policy),
    Check(
        "fork_approval",
        "fork-ci",
        "all_external_contributors",
        read_fork_approval,
        put("actions/permissions/fork-pr-contributor-approval", {"approval_policy": "all_external_contributors"}),
    ),
    Check(
        "private_vuln_reporting",
        "pvr",
        "on",
        read_enabled_endpoint("private-vulnerability-reporting"),
        put("private-vulnerability-reporting"),
    ),
    Check("vulnerability_alerts", "alerts", "on", read_vuln_alerts, put("vulnerability-alerts")),
    Check(
        "security_fixes",
        "fixes",
        "on",
        read_enabled_endpoint("automated-security-fixes"),
        put("automated-security-fixes"),
    ),
    Check(
        "workflow_token",
        "token",
        "read",
        read_workflow_token,
        put(
            "actions/permissions/workflow",
            {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
        ),
    ),
    Check("ruleset_main", "main", "ok", read_ruleset("ruleset_main"), apply_ruleset("ruleset_main")),
    Check("ruleset_tags", "tags", "ok", read_ruleset("ruleset_tags"), apply_ruleset("ruleset_tags")),
    Check("secret_scanning", "secrets", "on", read_security("secret_scanning"), apply_security("secret_scanning")),
    Check(
        "push_protection",
        "push",
        "on",
        read_security("secret_scanning_push_protection"),
        apply_security("secret_scanning_push_protection"),
    ),
]
CHECK_KEYS = [c.key for c in CHECKS]


# --- Report-only items -------------------------------------------------------


def report_workflow_linters(repo: Repo) -> str:
    """`none` without workflows, `ok` if a workflow runs actionlint or zizmor, else `missing`."""
    resp = repo.gh.get(f"repos/{repo.name}/contents/.github/workflows")
    if resp.status == 404:
        return "none"
    if not resp.ok or not isinstance(resp.data, list):
        raise ApiError(resp)
    files = [f for f in resp.data if f.get("type") == "file" and f.get("name", "").endswith((".yml", ".yaml"))]
    if not files:
        return "none"
    for item in files:
        file = repo.gh.get(f"repos/{repo.name}/contents/{item['path']}")
        if not file.ok or not isinstance(file.data, dict):
            continue
        text = base64.b64decode(file.data.get("content") or "").decode("utf-8", "replace")
        if LINTERS_RE.search(text):
            return "ok"
    return "missing"


SECURITY_POLICY_QUERY = (
    "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){isSecurityPolicyEnabled}}"
)


def report_security_policy(repo: Repo) -> str:
    owner, name = repo.name.split("/", 1)
    resp = repo.gh.call("POST", "graphql", graphql={"query": SECURITY_POLICY_QUERY, "owner": owner, "name": name})
    try:
        enabled = resp.data["data"]["repository"]["isSecurityPolicyEnabled"]
    except (KeyError, TypeError) as exc:
        raise ApiError(resp) from exc
    return "yes" if enabled else "no"


def report_outside_prs(repo: Repo, pr_pages: int) -> list[str]:
    """Logins of people without write access who opened a PR. Bots are left out."""
    pulls = repo.gh.pages(f"repos/{repo.name}/pulls?state=all", limit=pr_pages)
    outside = {
        pr["user"]["login"]
        for pr in pulls
        if pr.get("user")
        and pr["user"].get("type") != "Bot"
        and pr.get("author_association") not in INSIDE_ASSOCIATIONS
    }
    return sorted(outside)


# --- Audit and apply ---------------------------------------------------------


@dataclass
class Result:
    repo: str
    settings: dict[str, State] = field(default_factory=dict)
    report: dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    archived: bool = False

    @property
    def meets(self) -> bool:
        return not self.errors and all(s.ok is not False for s in self.settings.values())

    def gaps(self, skip: set[str]) -> list[Check]:
        """Checks to change. A setting the audit could not read is never changed.
        An archived repo is read-only, so nothing in it is changed."""
        if self.archived:
            return []
        return [
            c
            for c in CHECKS
            if c.key not in skip
            and (s := self.settings.get(c.key)) is not None
            and s.ok is False
            and not s.value.startswith("error: ")
        ]

    def to_json(self) -> dict:
        return {
            "repo": self.repo,
            "meets_baseline": self.meets,
            "archived": self.archived,
            "settings": {
                c.key: {"current": s.value, "desired": c.desired, "ok": s.ok}
                for c in CHECKS
                if (s := self.settings.get(c.key))
            },
            "report": self.report,
            "errors": self.errors,
            **({"changes": self.changes, "failures": self.failures} if self.changes or self.failures else {}),
        }


def read_check(repo: Repo, check: Check) -> State:
    try:
        return check.read(repo)
    except ApiError as exc:
        return State(f"error: {exc}", False)


def audit(repo: Repo, pr_pages: int, reports: bool = True) -> Result:
    result = Result(repo.name)
    try:
        result.archived = bool(repo.info().get("archived"))
    except ApiError as exc:
        result.errors.append(f"repo: {exc}")
        return result
    for check in CHECKS:
        state = read_check(repo, check)
        result.settings[check.key] = state
        if state.value.startswith("error: "):
            result.errors.append(f"{check.key}: {state.value[7:]}")
    if not reports:
        return result
    for key, fn in (
        ("workflow_linters", report_workflow_linters),
        ("security_policy", report_security_policy),
        ("outside_pr_authors", lambda r: report_outside_prs(r, pr_pages)),
    ):
        try:
            result.report[key] = fn(repo)
        except ApiError as exc:
            result.report[key] = f"error: {exc}"
    return result


def apply(repo: Repo, result: Result, skip: set[str]) -> Result:
    """Change each setting that misses the baseline, then read every one back."""
    todo = result.gaps(skip)
    for check in todo:
        resp = check.apply(repo)
        result.changes.append(check.key)
        if not resp.ok:
            result.failures.append(f"{check.key}: {resp.message}")
        repo.forget()
    for check in todo:
        if any(f.startswith(f"{check.key}:") for f in result.failures):
            continue
        state = read_check(repo, check)
        result.settings[check.key] = state
        if state.ok is not True:
            result.failures.append(f"{check.key}: still {state.value} after the change")
    return result


# --- Scope -------------------------------------------------------------------


def list_owner_repos(gh: Gh, owner: str) -> list[dict]:
    user = gh.get(f"users/{owner}")
    if not user.ok:
        raise ApiError(user)
    if user.data.get("type") == "Organization":
        return gh.pages(f"orgs/{owner}/repos?type=public")
    return gh.pages(f"users/{owner}/repos?type=owner")


def select_repos(gh: Gh, args: argparse.Namespace) -> tuple[list[str], list[str]]:
    """(repos in scope, notes on the repos skipped)."""
    if args.repos:
        listed = []
        for name in args.repos:
            if "/" not in name:
                name = f"{args.owner or login(gh)}/{name}"
            resp = gh.get(f"repos/{name}")
            if not resp.ok:
                raise ApiError(resp)
            listed.append(resp.data)
    else:
        listed = list_owner_repos(gh, args.owner or login(gh))
    keep, skipped = [], []
    for item in listed:
        name = item["full_name"]
        if item.get("private") or item.get("visibility", "public") != "public":
            skipped.append(f"{name} (not public)")
        elif item.get("fork") and not args.include_forks:
            skipped.append(f"{name} (fork)")
        elif item.get("archived") and not args.include_archived:
            skipped.append(f"{name} (archived)")
        else:
            keep.append(name)
    return sorted(keep, key=str.lower), skipped


def login(gh: Gh) -> str:
    resp = gh.get("user")
    if not resp.ok:
        raise ApiError(resp)
    return resp.data["login"]


# --- Output ------------------------------------------------------------------


def cell(state: State | None) -> str:
    if state is None:
        return "?"
    if state.ok is None:
        return NA
    if not state.ok:
        return f"NO({state.value})"
    # Keep the duplicate count of a ruleset, such as `ok x2`.
    return "ok" + state.value[2:] if state.value.startswith("ok ") else "ok"


def report_cell(value: object) -> str:
    if isinstance(value, list):
        return str(len(value))
    return str(value) if value is not None else "?"


def table(results: list[Result]) -> str:
    head = ["repo"] + [c.column for c in CHECKS] + ["linters", "security.md", "outside-prs"]
    rows = [head]
    for r in results:
        row = [r.repo.split("/", 1)[1]] + [cell(r.settings.get(c.key)) for c in CHECKS]
        row += [report_cell(r.report.get(k)) for k in ("workflow_linters", "security_policy", "outside_pr_authors")]
        rows.append(row)
    widths = [max(len(row[i]) for row in rows) for i in range(len(head))]
    return "\n".join("  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip() for row in rows)


def plan_lines(results: list[Result], skip: set[str]) -> list[str]:
    lines = []
    for r in results:
        for check in r.gaps(skip):
            lines.append(f"{r.repo}: {check.key} {r.settings[check.key].value} -> {check.desired}")
    return lines


def pr_warnings(results: list[Result], skip: set[str]) -> list[str]:
    """Repos where collaborators-only would block people who opened PRs before."""
    lines = []
    for r in results:
        authors = r.report.get("outside_pr_authors")
        if "pr_policy" in {c.key for c in r.gaps(skip)} and isinstance(authors, list) and authors:
            lines.append(f"{r.repo}: {len(authors)} outside PR author(s) blocked from now on: {', '.join(authors)}")
    return lines


# --- CLI ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    parser.add_argument("repos", nargs="*", metavar="REPO", help="owner/name or name; default: all public repos")
    parser.add_argument("--owner", help="user or org whose public repos to scan (default: the gh login)")
    parser.add_argument("--include-forks", action="store_true", help="include forked repos")
    parser.add_argument("--include-archived", action="store_true", help="include archived repos")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="audit, then list the changes apply would make")
    mode.add_argument("--apply", action="store_true", help="list the changes, then make them")
    parser.add_argument("--yes", action="store_true", help="with --apply: skip the confirmation prompt")
    parser.add_argument(
        "--skip", action="append", default=[], choices=CHECK_KEYS, metavar="SETTING", help="leave SETTING unchanged"
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument(
        "--jobs", type=int, default=DEFAULT_JOBS, help=f"repos to read at once (default {DEFAULT_JOBS})"
    )
    parser.add_argument("--pr-pages", type=int, default=5, help="pages of 100 PRs to scan for outside authors")
    return parser


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(prompt).strip().lower() == "yes"
    except EOFError:
        return False


def run(args: argparse.Namespace, gh: Gh, out=sys.stdout, err=sys.stderr) -> int:
    skip = set(args.skip)
    repos, skipped = select_repos(gh, args)
    jobs = max(1, min(args.jobs, 16))
    lock = threading.Lock()
    done = [0]

    def audit_one(name: str) -> tuple[Repo, Result]:
        repo = Repo(gh, name)
        result = audit(repo, args.pr_pages)
        with lock:
            done[0] += 1
            if not args.json and err.isatty():
                print(f"\raudited {done[0]}/{len(repos)}", end="", file=err, flush=True)
        return repo, result

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        pairs = list(pool.map(audit_one, repos))
    if not args.json and err.isatty() and repos:
        print(file=err)
    results = [r for _, r in pairs]

    if args.apply or args.plan:
        lines = plan_lines(results, skip)
        warnings = pr_warnings(results, skip)
        print(f"Planned changes ({len(lines)}):", file=err)
        for line in lines or ["(none: every repo meets the baseline)"]:
            print(f"  {line}", file=err)
        for line in warnings:
            print(f"WARNING {line}", file=err)
        for r in results:
            if r.archived and not r.meets:
                print(f"NOTE {r.repo}: archived, so read-only. No changes planned.", file=err)
        if args.plan or not lines:
            return emit(args, results, skipped, out, err)
        if not args.yes and not confirm("Type yes to apply these changes: "):
            print("Nothing changed. Pass --yes to apply without a prompt.", file=err)
            return 2
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(lambda pair: apply(pair[0], pair[1], skip), [p for p in pairs if p[1].gaps(skip)]))
        changed = sum(len(r.changes) for r in results)
        failed = [f"{r.repo}: {f}" for r in results for f in r.failures]
        print(f"Applied {changed - len(failed)} of {changed} change(s).", file=err)
        for line in failed:
            print(f"FAILED {line}", file=err)
        emit(args, results, skipped, out, err)
        return 1 if failed else 0

    return emit(args, results, skipped, out, err)


def emit(args: argparse.Namespace, results: list[Result], skipped: list[str], out, err) -> int:
    meeting = sum(r.meets for r in results)
    if args.json:
        doc = {
            "repos": [r.to_json() for r in results],
            "skipped": skipped,
            "summary": {"audited": len(results), "meet_baseline": meeting},
        }
        print(json.dumps(doc, indent=2), file=out)
    else:
        if results:
            print(table(results), file=out)
        print(f"\n{meeting} of {len(results)} repos meet the baseline.", file=out)
        if skipped:
            reasons = Counter(note.rsplit(" (", 1)[1].rstrip(")") for note in skipped)
            counts = ", ".join(f"{n} {reason}" for reason, n in sorted(reasons.items()))
            print(f"Skipped {len(skipped)} ({counts}). --json lists them.", file=out)
        for r in results:
            for e in r.errors:
                print(f"ERROR {r.repo}: {e}", file=out)
    return 0 if meeting == len(results) else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.yes and not args.apply:
        print("harden.py: --yes only works with --apply", file=sys.stderr)
        return 2
    try:
        return run(args, Gh())
    except GhError as exc:
        print(f"harden.py: {exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"harden.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
