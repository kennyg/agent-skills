"""Tests for harden.py against a fake GitHub. No test calls the real API.

Run with: python3 -m unittest discover -s skills/github-harden/tests
The fake stands in for `subprocess.run`. It answers `gh api --include` calls
from an in-memory repo and changes that repo on writes, so apply and the
read-back after it run end to end.
"""

from __future__ import annotations

import base64
import copy
import io
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import harden  # noqa: E402

COMPLIANT = {
    "pull_request_creation_policy": "collaborators_only",
    "fork_approval": "all_external_contributors",
    "pvr": True,
    "alerts": True,
    "fixes": True,
    "workflow": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
    "secret_scanning": "enabled",
    "push_protection": "enabled",
    "rulesets": [
        {
            "id": 1,
            "name": "Protect main",
            "target": "branch",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
            "bypass_actors": [],
        },
        {
            "id": 2,
            "name": "Protect release tags",
            "target": "tag",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
            "rules": [{"type": t} for t in ("creation", "update", "deletion", "non_fast_forward")],
            "bypass_actors": [dict(harden.ADMIN_BYPASS)],
        },
    ],
    "workflows": {},
    "security_policy": False,
    "pulls": [],
}

OPEN = {
    "pull_request_creation_policy": "all",
    "fork_approval": "first_time_contributors",
    "pvr": False,
    "alerts": False,
    "fixes": False,
    "workflow": {"default_workflow_permissions": "write", "can_approve_pull_request_reviews": True},
    "secret_scanning": "disabled",
    "push_protection": "disabled",
    "rulesets": [],
    "workflows": {"ci.yml": "jobs:\n  test:\n    steps:\n      - run: make test\n"},
    "security_policy": False,
    "pulls": [
        {"user": {"login": "kennyg", "type": "User"}, "author_association": "OWNER"},
        {"user": {"login": "stranger", "type": "User"}, "author_association": "CONTRIBUTOR"},
        {"user": {"login": "dependabot[bot]", "type": "Bot"}, "author_association": "NONE"},
        {"user": {"login": "friend", "type": "User"}, "author_association": "COLLABORATOR"},
    ],
}


def http(status: int, data: object = None, headers: dict | None = None) -> SimpleNamespace:
    reason = {200: "OK", 201: "Created", 204: "No Content", 404: "Not Found"}.get(status, "Error")
    head = [f"HTTP/2.0 {status} {reason}", "Content-Type: application/json"]
    head += [f"{k}: {v}" for k, v in (headers or {}).items()]
    body = "" if data is None else json.dumps(data)
    return SimpleNamespace(stdout="\r\n".join(head) + "\r\n\r\n" + body, stderr="", returncode=0 if status < 400 else 1)


class FakeGitHub:
    """Answers `gh api` argv lists the way GitHub would, for a few repos."""

    def __init__(self, repos: dict[str, dict], owner: str = "me"):
        self.owner = owner
        self.repos = {name: copy.deepcopy(state) for name, state in repos.items()}
        self.extra: dict[str, dict] = {}  # name -> repo fields such as fork or archived
        self.calls: list[tuple[str, str, object]] = []
        self.fail: set[tuple[str, str]] = set()  # (method, path) that answer 422
        self.ignore: set[tuple[str, str]] = set()  # (method, path) that answer 204 but change nothing
        self.next_id = 100

    @property
    def writes(self) -> list[tuple[str, str, object]]:
        return [c for c in self.calls if c[0] != "GET" and c[1] != "graphql"]

    def __call__(self, argv, input=None, capture_output=False, text=False, check=False, **kw):
        assert isinstance(argv, list), "argv must be a list"
        assert "shell" not in kw, "never run through a shell"
        assert argv[:3] == ["gh", "api", "--include"], argv
        method = argv[argv.index("--method") + 1]
        path = argv[argv.index("--method") + 2]
        fields = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "-f")
        body = json.loads(input) if input else None
        self.calls.append((method, path, body or fields or None))
        if (method, path) in self.fail:
            return http(422, {"message": "Validation Failed"})
        return self.route(method, path, body, fields)

    def info(self, name: str) -> dict:
        s = self.repos[name]
        return {
            "full_name": name,
            "private": False,
            "visibility": "public",
            "fork": False,
            "archived": False,
            "pull_request_creation_policy": s["pull_request_creation_policy"],
            "security_and_analysis": {
                "secret_scanning": {"status": s["secret_scanning"]},
                "secret_scanning_push_protection": {"status": s["push_protection"]},
            },
            **self.extra.get(name, {}),
        }

    def route(self, method: str, path: str, body: object, fields: dict) -> SimpleNamespace:
        url = urlsplit(path)
        if path == "user":
            return http(200, {"login": self.owner})
        if url.path == f"users/{self.owner}":
            return http(200, {"login": self.owner, "type": "User"})
        if url.path == f"users/{self.owner}/repos":
            page = int(re.search(r"(?:^|&)page=(\d+)", url.query).group(1))
            return http(200, [self.info(n) for n in self.repos] if page == 1 else [])
        if path == "graphql":
            name = f"{fields['owner']}/{fields['name']}"
            enabled = self.repos[name]["security_policy"]
            return http(200, {"data": {"repository": {"isSecurityPolicyEnabled": enabled}}})
        m = re.match(r"repos/([^/]+/[^/]+)(?:/(.*))?$", url.path)
        if not m or m.group(1) not in self.repos:
            return http(404, {"message": "Not Found"})
        name, rest = m.group(1), m.group(2) or ""
        if (method, path) in self.ignore:
            return http(204)
        return self.repo_route(name, self.repos[name], method, rest, url.query, body)

    def repo_route(self, name, s, method, rest, query, body) -> SimpleNamespace:
        if rest == "":
            if method == "PATCH":
                if "pull_request_creation_policy" in body:
                    s["pull_request_creation_policy"] = body["pull_request_creation_policy"]
                for feature, value in (body.get("security_and_analysis") or {}).items():
                    key = "push_protection" if feature.endswith("push_protection") else "secret_scanning"
                    s[key] = value["status"]
            return http(200, self.info(name))
        if rest == "actions/permissions/fork-pr-contributor-approval":
            if method == "PUT":
                s["fork_approval"] = body["approval_policy"]
                return http(204)
            if s["fork_approval"] is None:
                return http(404, {"message": "Not Found"})
            return http(200, {"approval_policy": s["fork_approval"]})
        if rest == "private-vulnerability-reporting":
            if method == "PUT":
                s["pvr"] = True
                return http(204)
            return http(200, {"enabled": s["pvr"]})
        if rest == "vulnerability-alerts":
            if method == "PUT":
                s["alerts"] = True
                return http(204)
            return http(204) if s["alerts"] else http(404, {"message": "Vulnerability alerts are disabled."})
        if rest == "automated-security-fixes":
            if method == "PUT":
                if not s["alerts"]:
                    return http(422, {"message": "Vulnerability alerts must be enabled first"})
                s["fixes"] = True
                return http(204)
            return http(200, {"enabled": s["fixes"], "paused": False})
        if rest == "actions/permissions/workflow":
            if method == "PUT":
                s["workflow"] = body
                return http(204)
            return http(200, s["workflow"])
        if rest == "rulesets":
            if method == "POST":
                ruleset = {**body, "id": self.next_id}
                self.next_id += 1
                s["rulesets"].append(ruleset)
                return http(201, ruleset)
            return http(200, [{"id": r["id"], "name": r["name"]} for r in s["rulesets"]])
        if m := re.match(r"rulesets/(\d+)$", rest):
            ruleset = next(r for r in s["rulesets"] if r["id"] == int(m.group(1)))
            if method == "PUT":
                ruleset.clear()
                ruleset.update({**body, "id": int(m.group(1))})
            return http(200, ruleset)
        if rest == "contents/.github/workflows":
            if not s["workflows"]:
                return http(404, {"message": "Not Found"})
            items = [{"name": f, "path": f".github/workflows/{f}", "type": "file"} for f in s["workflows"]]
            return http(200, items)
        if m := re.match(r"contents/\.github/workflows/(.+)$", rest):
            content = base64.b64encode(s["workflows"][m.group(1)].encode()).decode()
            return http(200, {"content": content, "encoding": "base64"})
        if rest == "pulls":
            page = int(re.search(r"(?:^|&)page=(\d+)", query).group(1))
            return http(200, s["pulls"] if page == 1 else [])
        return http(404, {"message": "Not Found"})


def make_gh(fake: FakeGitHub) -> harden.Gh:
    return harden.Gh(run=fake, sleep=lambda s: None)


def run_cli(fake: FakeGitHub, *argv: str) -> tuple[int, str, str]:
    args = harden.build_parser().parse_args(list(argv))
    out, err = io.StringIO(), io.StringIO()
    code = harden.run(args, make_gh(fake), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


class ParseResponse(unittest.TestCase):
    def test_status_headers_and_json_body(self) -> None:
        resp = harden.parse_response(http(200, {"enabled": True}, {"X-RateLimit-Remaining": "12"}).stdout)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers["x-ratelimit-remaining"], "12")
        self.assertEqual(resp.data, {"enabled": True})

    def test_empty_body(self) -> None:
        resp = harden.parse_response("HTTP/1.1 204 No Content\nServer: github.com\n\n")
        self.assertEqual((resp.status, resp.data), (204, None))
        self.assertTrue(resp.ok)

    def test_no_status_line_means_no_response(self) -> None:
        self.assertEqual(harden.parse_response("").status, 0)

    def test_message_from_body(self) -> None:
        resp = harden.parse_response(http(404, {"message": "Vulnerability alerts are disabled."}).stdout)
        self.assertEqual(resp.message, "Vulnerability alerts are disabled.")


class GhRunner(unittest.TestCase):
    def test_body_goes_on_stdin_and_argv_is_a_list(self) -> None:
        seen = {}

        def run(argv, input=None, **kw):
            seen.update(argv=argv, input=input, kw=kw)
            return http(204)

        harden.Gh(run=run).call("PUT", "repos/a/b/actions/permissions/workflow", {"x": 1})
        self.assertEqual(seen["argv"][-2:], ["--input", "-"])
        self.assertEqual(json.loads(seen["input"]), {"x": 1})
        self.assertNotIn("shell", seen["kw"])

    def test_waits_for_retry_after_then_retries(self) -> None:
        answers = [http(429, {"message": "slow down"}, {"Retry-After": "7"}), http(200, {"ok": 1})]
        slept = []
        gh = harden.Gh(run=lambda argv, **kw: answers.pop(0), sleep=slept.append)
        self.assertEqual(gh.get("repos/a/b").status, 200)
        self.assertEqual(slept, [7.0])

    def test_waits_for_primary_reset(self) -> None:
        limited = http(
            403, {"message": "API rate limit exceeded"}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1010"}
        )
        answers = [limited, http(200, {})]
        slept = []
        gh = harden.Gh(run=lambda argv, **kw: answers.pop(0), sleep=slept.append, clock=lambda: 1000.0)
        gh.get("repos/a/b")
        self.assertEqual(slept, [11.0])

    def test_gives_up_when_the_reset_is_too_far(self) -> None:
        limited = http(403, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "99999"})
        slept = []
        gh = harden.Gh(run=lambda argv, **kw: limited, sleep=slept.append, clock=lambda: 0.0)
        self.assertEqual(gh.get("repos/a/b").status, 403)
        self.assertEqual(slept, [])

    def test_plain_403_is_not_retried(self) -> None:
        calls = []
        gh = harden.Gh(run=lambda argv, **kw: calls.append(1) or http(403, {"message": "Must have admin rights"}))
        self.assertEqual(gh.get("repos/a/b").message, "Must have admin rights")
        self.assertEqual(len(calls), 1)

    def test_network_error_is_retried_then_reported(self) -> None:
        fail = SimpleNamespace(stdout="", stderr="net/http: TLS handshake timeout\n", returncode=1)
        answers = [fail, http(200, {})]
        gh = harden.Gh(run=lambda argv, **kw: answers.pop(0), sleep=lambda s: None)
        self.assertEqual(gh.get("repos/a/b").status, 200)
        gh = harden.Gh(run=lambda argv, **kw: fail, sleep=lambda s: None)
        resp = gh.get("repos/a/b")
        self.assertEqual((resp.status, resp.message), (0, "net/http: TLS handshake timeout"))


class Audit(unittest.TestCase):
    def audit(self, state: dict) -> harden.Result:
        fake = FakeGitHub({"me/r": state})
        return harden.audit(harden.Repo(make_gh(fake), "me/r"), pr_pages=5)

    def test_compliant_repo_meets_the_baseline(self) -> None:
        result = self.audit(COMPLIANT)
        self.assertTrue(result.meets, result.to_json())
        self.assertEqual(result.gaps(set()), [])

    def test_open_repo_misses_every_setting(self) -> None:
        result = self.audit(OPEN)
        self.assertFalse(result.meets)
        self.assertEqual([c.key for c in result.gaps(set())], harden.CHECK_KEYS)
        self.assertEqual(result.settings["vulnerability_alerts"].value, "off")
        self.assertEqual(result.settings["workflow_token"].value, "write+approve")
        self.assertEqual(result.settings["ruleset_main"].value, "missing")

    def test_missing_feature_is_not_applicable(self) -> None:
        result = self.audit({**COMPLIANT, "fork_approval": None})
        self.assertIsNone(result.settings["fork_approval"].ok)
        self.assertTrue(result.meets)

    def test_report_only_items(self) -> None:
        report = self.audit(OPEN).report
        self.assertEqual(report["workflow_linters"], "missing")
        self.assertEqual(report["security_policy"], "no")
        self.assertEqual(report["outside_pr_authors"], ["stranger"])
        linted = {**OPEN, "workflows": {"lint.yml": "steps:\n  - uses: rhysd/actionlint@v1\n"}}
        self.assertEqual(self.audit(linted).report["workflow_linters"], "ok")
        self.assertEqual(self.audit(COMPLIANT).report["workflow_linters"], "none")

    def test_ruleset_that_differs_is_named(self) -> None:
        state = copy.deepcopy(COMPLIANT)
        state["rulesets"][1]["bypass_actors"] = []
        state["rulesets"][1]["rules"] = [{"type": "deletion"}]
        result = self.audit(state)
        self.assertEqual(result.settings["ruleset_tags"].value, "differs(rules,bypass)")

    def test_read_error_is_reported_and_never_planned(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        fake.fail.add(("GET", "repos/me/r/private-vulnerability-reporting"))
        result = harden.audit(harden.Repo(make_gh(fake), "me/r"), pr_pages=5)
        self.assertIn("private_vuln_reporting: Validation Failed", result.errors)
        self.assertNotIn("private_vuln_reporting", [c.key for c in result.gaps(set())])


class Apply(unittest.TestCase):
    def test_apply_fixes_every_gap_and_reads_back(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        code, out, err = run_cli(fake, "--apply", "--yes", "--json")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertTrue(doc["repos"][0]["meets_baseline"])
        self.assertEqual(doc["repos"][0]["failures"], [])
        self.assertIn("Applied 10 of 10 change(s).", err)
        # A second audit finds nothing to do.
        self.assertEqual(run_cli(fake)[0], 0)

    def test_apply_changes_only_what_differs(self) -> None:
        fake = FakeGitHub({"me/r": {**COMPLIANT, "pvr": False}})
        code, _, err = run_cli(fake, "--apply", "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.writes, [("PUT", "repos/me/r/private-vulnerability-reporting", None)])

    def test_compliant_repo_gets_no_writes(self) -> None:
        fake = FakeGitHub({"me/r": COMPLIANT})
        code, _, err = run_cli(fake, "--apply", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes, [])
        self.assertIn("(none: every repo meets the baseline)", err)

    def test_alerts_go_on_before_security_fixes(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        run_cli(fake, "--apply", "--yes")
        paths = [p for _, p, _ in fake.writes]
        self.assertLess(
            paths.index("repos/me/r/vulnerability-alerts"), paths.index("repos/me/r/automated-security-fixes")
        )

    def test_skip_leaves_a_setting_alone(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        code, _, _ = run_cli(fake, "--apply", "--yes", "--skip", "pr_policy")
        self.assertEqual(fake.repos["me/r"]["pull_request_creation_policy"], "all")
        self.assertEqual(code, 0)  # Every change it made held.
        self.assertEqual(run_cli(fake)[0], 1)  # The audit still finds the skipped setting.

    def test_failed_write_is_reported(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        fake.fail.add(("PUT", "repos/me/r/private-vulnerability-reporting"))
        code, _, err = run_cli(fake, "--apply", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("FAILED me/r: private_vuln_reporting: Validation Failed", err)

    def test_write_that_does_not_hold_is_caught_on_read_back(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        fake.ignore.add(("PUT", "repos/me/r/actions/permissions/workflow"))
        code, _, err = run_cli(fake, "--apply", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("FAILED me/r: workflow_token: still write+approve after the change", err)

    def test_apply_without_yes_and_no_tty_changes_nothing(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        code, _, err = run_cli(fake, "--apply")
        self.assertEqual(code, 2)
        self.assertEqual(fake.writes, [])
        self.assertIn("Planned changes (10):", err)

    def test_plan_lists_changes_and_warns_about_outside_authors(self) -> None:
        fake = FakeGitHub({"me/r": OPEN})
        code, _, err = run_cli(fake, "--plan")
        self.assertEqual(fake.writes, [])
        self.assertEqual(code, 1)
        self.assertIn("me/r: pr_policy all -> collaborators_only", err)
        self.assertIn("WARNING me/r: 1 outside PR author(s) blocked from now on: stranger", err)
        self.assertNotIn("dependabot", err)
        self.assertNotIn("friend", err)

    def test_no_warning_when_pr_policy_is_skipped(self) -> None:
        _, _, err = run_cli(FakeGitHub({"me/r": OPEN}), "--plan", "--skip", "pr_policy")
        self.assertNotIn("WARNING", err)


class Rulesets(unittest.TestCase):
    def test_missing_rulesets_are_created_once(self) -> None:
        fake = FakeGitHub({"me/r": {**COMPLIANT, "rulesets": []}})
        run_cli(fake, "--apply", "--yes")
        run_cli(fake, "--apply", "--yes")
        names = [r["name"] for r in fake.repos["me/r"]["rulesets"]]
        self.assertEqual(sorted(names), ["Protect main", "Protect release tags"])
        tags = next(r for r in fake.repos["me/r"]["rulesets"] if r["target"] == "tag")
        self.assertEqual(tags["bypass_actors"], [harden.ADMIN_BYPASS])
        self.assertEqual(tags["conditions"]["ref_name"]["include"], ["refs/tags/v*"])

    def test_existing_ruleset_is_updated_not_duplicated(self) -> None:
        state = copy.deepcopy(COMPLIANT)
        main = state["rulesets"][0]
        main["enforcement"] = "disabled"
        main["rules"] = [{"type": "deletion"}, {"type": "required_linear_history"}]
        fake = FakeGitHub({"me/r": state})
        code, _, err = run_cli(fake, "--apply", "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.writes[0][:2], ("PUT", "repos/me/r/rulesets/1"))
        rulesets = fake.repos["me/r"]["rulesets"]
        self.assertEqual(len(rulesets), 2)
        self.assertEqual(rulesets[0]["enforcement"], "active")
        # The extra rule the owner added stays.
        types = [r["type"] for r in rulesets[0]["rules"]]
        self.assertEqual(types, ["deletion", "required_linear_history", "non_fast_forward"])

    def test_post_with_a_lost_reply_is_not_sent_again(self) -> None:
        fake = FakeGitHub({"me/r": {**COMPLIANT, "rulesets": []}})

        def lossy(argv, **kw):
            reply = fake(argv, **kw)
            if "POST" in argv and "repos/me/r/rulesets" in argv:
                return SimpleNamespace(stdout="", stderr="unexpected EOF\n", returncode=1)
            return reply

        args = harden.build_parser().parse_args(["--apply", "--yes"])
        out, err = io.StringIO(), io.StringIO()
        code = harden.run(args, harden.Gh(run=lossy, sleep=lambda s: None), out=out, err=err)
        posts = [c for c in fake.writes if c[0] == "POST"]
        self.assertEqual(len(posts), 2)  # One per missing ruleset, never a resend.
        self.assertEqual(code, 1)
        self.assertIn("FAILED me/r: ruleset_main: unexpected EOF", err.getvalue())
        # The next run finds the rulesets that did land and creates nothing.
        self.assertEqual(run_cli(fake, "--apply", "--yes")[0], 0)
        self.assertEqual(len(fake.repos["me/r"]["rulesets"]), 2)

    def test_duplicate_ruleset_shows_in_the_table(self) -> None:
        state = copy.deepcopy(COMPLIANT)
        state["rulesets"].append({**state["rulesets"][0], "id": 9})
        _, out, _ = run_cli(FakeGitHub({"me/r": state}))
        self.assertIn("ok x2", out.splitlines()[1])

    def test_body_moves_the_ref_out_of_exclude(self) -> None:
        spec = harden.RULESETS["ruleset_main"]
        existing = {"conditions": {"ref_name": {"include": [], "exclude": ["~DEFAULT_BRANCH", "dev"]}}}
        body = harden.ruleset_body(spec, existing)
        self.assertEqual(body["conditions"]["ref_name"], {"include": ["~DEFAULT_BRANCH"], "exclude": ["dev"]})


class Scope(unittest.TestCase):
    def fake(self) -> FakeGitHub:
        fake = FakeGitHub({"me/a": COMPLIANT, "me/fork": COMPLIANT, "me/old": COMPLIANT})
        fake.extra = {"me/fork": {"fork": True}, "me/old": {"archived": True}}
        return fake

    def test_forks_and_archived_are_skipped_by_default(self) -> None:
        code, out, _ = run_cli(self.fake(), "--json")
        doc = json.loads(out)
        self.assertEqual([r["repo"] for r in doc["repos"]], ["me/a"])
        self.assertEqual(doc["skipped"], ["me/fork (fork)", "me/old (archived)"])
        self.assertEqual(code, 0)

    def test_flags_include_them(self) -> None:
        _, out, _ = run_cli(self.fake(), "--json", "--include-forks", "--include-archived")
        self.assertEqual(len(json.loads(out)["repos"]), 3)

    def test_archived_repo_gets_no_planned_changes(self) -> None:
        fake = FakeGitHub({"me/old": OPEN})
        fake.extra = {"me/old": {"archived": True}}
        code, out, err = run_cli(fake, "--apply", "--yes", "--include-archived", "--json")
        self.assertIn("Planned changes (0):", err)
        self.assertIn("NOTE me/old: archived, so read-only. No changes planned.", err)
        self.assertEqual(fake.writes, [])
        self.assertTrue(json.loads(out)["repos"][0]["archived"])
        self.assertEqual(code, 1)  # The repo still misses the baseline.

    def test_named_repos_and_bare_names(self) -> None:
        _, out, _ = run_cli(self.fake(), "--json", "a", "me/old", "--owner", "me")
        doc = json.loads(out)
        self.assertEqual([r["repo"] for r in doc["repos"]], ["me/a"])
        self.assertEqual(doc["skipped"], ["me/old (archived)"])

    def test_table_has_one_row_per_repo(self) -> None:
        _, out, _ = run_cli(FakeGitHub({"me/a": COMPLIANT, "me/b": OPEN}))
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("repo"))
        self.assertTrue(lines[1].startswith("a "))
        self.assertIn("NO(all)", lines[2])
        self.assertIn("1 of 2 repos meet the baseline.", out)


class Cli(unittest.TestCase):
    def test_script_runs_through_its_shebang(self) -> None:
        proc = subprocess.run([str(SCRIPTS / "harden.py"), "--help"], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--apply", proc.stdout)

    def test_yes_needs_apply(self) -> None:
        self.assertEqual(harden.main(["--yes"]), 2)


if __name__ == "__main__":
    unittest.main()
