from __future__ import annotations

import argparse
import json
import sys

from .manager import PowerBiMcpManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="powerbi-mcp-manager",
        description="Manage a local @microsoft/powerbi-modeling-mcp install.",
    )
    parser.add_argument(
        "--project-dir",
        help="Base folder used for mcps and .npm-cache. Defaults to the current folder.",
    )
    parser.add_argument(
        "--package",
        help="npm package to manage. Defaults to @microsoft/powerbi-modeling-mcp.",
    )
    parser.add_argument(
        "--tag",
        help="npm dist-tag to track. Defaults to latest.",
    )
    parser.add_argument(
        "--managed-dir",
        help="Folder where the npm package is installed.",
    )
    parser.add_argument(
        "--npm-cache-dir",
        help="Folder used as npm cache.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show installed and remote versions.")
    status.add_argument("--json", action="store_true", help="Print status as JSON.")

    check = subparsers.add_parser(
        "check",
        help="Exit 0 when installed version matches the tracked npm version.",
    )
    check.add_argument("--json", action="store_true", help="Print status as JSON.")

    install = subparsers.add_parser("install", help="Install the package locally.")
    install.add_argument("version", nargs="?", help="Version or npm tag to install.")

    subparsers.add_parser("update", help="Install latest only when needed.")
    subparsers.add_parser("path", help="Print the local MCP executable path.")
    subparsers.add_parser("config", help="Print an MCP server JSON snippet.")

    return parser


def make_manager(args: argparse.Namespace) -> PowerBiMcpManager:
    return PowerBiMcpManager(
        project_dir=args.project_dir,
        package_name=args.package,
        tag=args.tag,
        managed_dir=args.managed_dir,
        npm_cache_dir=args.npm_cache_dir,
    )


def print_status(status, as_json: bool) -> None:
    if as_json:
        print(json.dumps(status.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Package: {status.package_name}")
    print(f"Tracked tag: {status.tracked_tag}")
    print(f"Latest version: {status.latest_version}")
    print(f"Installed version: {status.installed_version or 'none'}")
    print(f"State: {status.state}")
    print(f"Managed dir: {status.managed_dir}")
    print(f"NPM cache: {status.npm_cache_dir}")
    if status.installed:
        print(f"Executable: {status.installed.executable_path}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    manager = make_manager(args)

    try:
        if args.command == "status":
            print_status(manager.status(), args.json)
            return 0

        if args.command == "check":
            status = manager.status()
            print_status(status, args.json)

            if status.state == "up-to-date":
                return 0
            if status.state == "update-available":
                return 1
            return 2

        if args.command == "install":
            installed = manager.install(args.version)
            print(f"Installed {installed.name}@{installed.version}")
            print(f"Executable: {installed.executable_path}")
            return 0

        if args.command == "update":
            result = manager.update()
            if result.updated:
                print(f"Updated {result.previous_version or 'none'} -> {result.installed.version}")
            else:
                print(
                    f"{manager.package_name} is already up to date "
                    f"({result.installed.version})."
                )
            print(f"Executable: {result.installed.executable_path}")
            return 0

        if args.command == "path":
            print(manager.executable_path())
            return 0

        if args.command == "config":
            print(json.dumps(manager.mcp_config(), indent=2, ensure_ascii=False))
            return 0

        parser.error(f"Unknown command: {args.command}")
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
