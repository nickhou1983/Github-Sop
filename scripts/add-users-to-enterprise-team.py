#!/usr/bin/env python3
"""Batch add GitHub EMU users to an Enterprise Team.

Usage:
    export GITHUB_TOKEN="github_pat_xxx"
    python3 scripts/add-users-to-enterprise-team.py \
        --enterprise <enterprise-slug> \
        --team <enterprise-team-slug> \
        --file scripts/users-sample.csv
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, NamedTuple


API_VERSION = "2022-11-28"
DEFAULT_API_URL = "https://api.github.com"


class ApiResult(NamedTuple):
    status_code: int
    message: str
    state: str | None = None


class Summary(NamedTuple):
    success_count: int
    fail_count: int
    skipped_count: int
    total_count: int


def read_users_from_csv(filepath: str | Path) -> list[str]:
    users: list[str] = []
    seen: set[str] = set()

    with Path(filepath).open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.reader(csv_file)
        for row in reader:
            if not row:
                continue

            username = row[0].strip()
            if not username or username.lower() == "username":
                continue
            if username in seen:
                continue

            users.append(username)
            seen.add(username)

    return users


def build_membership_url(
    enterprise: str,
    team_slug: str,
    username: str,
    api_url: str = DEFAULT_API_URL,
) -> str:
    return (
        f"{api_url.rstrip('/')}/enterprises/{enterprise}/teams/"
        f"{team_slug}/memberships/{username}"
    )


def get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("错误: 请先设置环境变量 GITHUB_TOKEN", file=sys.stderr)
        print(
            "Token 需要具备管理 Enterprise Team 成员关系的权限。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return token


def add_user_to_enterprise_team(
    enterprise: str,
    team_slug: str,
    username: str,
    role: str,
    token: str,
    api_url: str = DEFAULT_API_URL,
) -> ApiResult:
    url = build_membership_url(enterprise, team_slug, username, api_url)
    payload = json.dumps({"role": role}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="PUT",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "github-sop-enterprise-team-bulk-add",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
            return ApiResult(
                status_code=response.status,
                message=body.get("message", "OK"),
                state=body.get("state"),
            )
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            message = json.loads(body).get("message", body)
        except json.JSONDecodeError:
            message = body or str(error)
        return ApiResult(status_code=error.code, message=message)
    except urllib.error.URLError as error:
        return ApiResult(status_code=0, message=str(error.reason))


def error_hint(status_code: int) -> str:
    hints = {
        403: "请检查 GITHUB_TOKEN 权限是否可管理 Enterprise Team 成员。",
        404: "请检查 enterprise slug、Enterprise Team slug 或 API 可访问性。",
        422: "请检查用户是否属于该 Enterprise，或用户名是否为正确的 EMU 用户名。",
    }
    return hints.get(status_code, "")


def process_users(
    enterprise: str,
    team_slug: str,
    users: list[str],
    role: str,
    token: str,
    dry_run: bool = False,
    add_membership: Callable[..., ApiResult] = add_user_to_enterprise_team,
) -> Summary:
    success_count = 0
    fail_count = 0
    skipped_count = 0

    for username in users:
        if dry_run:
            print(f"  - DRY-RUN: 将添加 {username} 到 {team_slug}，角色 {role}")
            skipped_count += 1
            continue

        result = add_membership(enterprise, team_slug, username, role, token)
        if result.status_code in (200, 201):
            state = f", state={result.state}" if result.state else ""
            print(f"  ✓ {username} - HTTP {result.status_code}{state}")
            success_count += 1
        else:
            hint = error_hint(result.status_code)
            hint_text = f" ({hint})" if hint else ""
            print(
                f"  ✗ {username} - HTTP {result.status_code}: "
                f"{result.message}{hint_text}"
            )
            fail_count += 1

        time.sleep(0.5)

    return Summary(
        success_count=success_count,
        fail_count=fail_count,
        skipped_count=skipped_count,
        total_count=len(users),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量将 GitHub EMU 用户添加到指定 Enterprise Team"
    )
    parser.add_argument("--enterprise", required=True, help="GitHub Enterprise slug")
    parser.add_argument("--team", required=True, help="Enterprise Team slug")
    parser.add_argument("--file", required=True, help="包含 GitHub 用户名的 CSV 文件路径")
    parser.add_argument(
        "--role",
        choices=("member", "maintainer"),
        default="member",
        help="用户在 Enterprise Team 中的角色，默认为 member",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要添加的用户，不调用 GitHub API",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    users = read_users_from_csv(args.file)

    if not users:
        print("错误: CSV 文件中没有找到有效用户名", file=sys.stderr)
        return 1

    token = "" if args.dry_run else get_github_token()

    print(f"Enterprise: {args.enterprise}")
    print(f"Enterprise Team: {args.team}")
    print(f"Role: {args.role}")
    print(f"Users: {len(users)}")
    print(f"Dry run: {'yes' if args.dry_run else 'no'}")
    print("-" * 60)

    summary = process_users(
        enterprise=args.enterprise,
        team_slug=args.team,
        users=users,
        role=args.role,
        token=token,
        dry_run=args.dry_run,
    )

    print("-" * 60)
    print(
        "完成: "
        f"成功 {summary.success_count}, "
        f"失败 {summary.fail_count}, "
        f"跳过 {summary.skipped_count}, "
        f"总计 {summary.total_count}"
    )

    return 0 if summary.fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())