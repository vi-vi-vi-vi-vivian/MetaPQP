"""Local CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
from itertools import product

from portal_audit.adapters.auth.huaweicloud import VALIDATION_URLS
from portal_audit.bootstrap import build_auth_provider, build_page_audit_runner
from portal_audit.domain.models import (
    AuthMode,
    ModelExecutionMode,
    PageAuditRequest,
    PageTarget,
)
from portal_audit.settings import Settings

DEFAULT_DEVICES = ("desktop", "mobile")
DEFAULT_LOCALES = ("zh-CN", "en-US")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meta-pqp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    page = subparsers.add_parser("page", help="run one page audit")
    page.add_argument("--url", required=True)
    page.add_argument("--product")
    page.add_argument(
        "--page-id",
        help="stable semantic page name, for example awareness or purchase",
    )
    page.add_argument(
        "--device",
        choices=DEFAULT_DEVICES,
        help="restrict the default desktop+mobile matrix to one device",
    )
    page.add_argument(
        "--locale",
        choices=DEFAULT_LOCALES,
        help="restrict the default zh-CN+en-US matrix to one locale",
    )
    page.add_argument("--stage")
    page.add_argument("--archetype")
    page.add_argument("--auth", choices=[item.value for item in AuthMode], default="auto")
    page.add_argument(
        "--model-execution",
        choices=[item.value for item in ModelExecutionMode],
        default=ModelExecutionMode.GROUPED.value,
        help="run model checks one-by-one or in configured semantic groups",
    )
    auth = subparsers.add_parser("auth", help="manage browser authentication")
    auth_subparsers = auth.add_subparsers(dest="auth_command", required=True)
    login = auth_subparsers.add_parser("login", help="create or refresh Huawei Cloud login state")
    login.add_argument("--site", choices=["cn", "intl"])
    login.add_argument("--headed", action="store_true")
    login.add_argument("--force", action="store_true")
    return parser


async def _run_page(args: argparse.Namespace) -> int:
    runner = build_page_audit_runner()
    results = []
    for device, locale in requested_variants(args.device, args.locale):
        result = await runner.run(
            PageAuditRequest(
                url=args.url,
                product=args.product,
                page_id=args.page_id,
                device=device,
                locale=locale,
                journey_stage=args.stage,
                page_archetype=args.archetype,
                model_execution_mode=args.model_execution,
                auth_mode=args.auth,
            )
        )
        results.append(
            {
                "device": device,
                "locale": locale,
                "job_id": result.job_id,
                "output_dir": result.output_dir,
            }
        )
    payload = results[0] if len(results) == 1 else {"run_count": len(results), "runs": results}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def requested_variants(
    device: str | None,
    locale: str | None,
) -> list[tuple[str, str]]:
    devices = (device,) if device else DEFAULT_DEVICES
    locales = (locale,) if locale else DEFAULT_LOCALES
    return list(product(devices, locales))


async def _run_auth_login(args: argparse.Namespace) -> int:
    settings = Settings()
    provider = build_auth_provider(
        settings,
        headless=not args.headed,
        force_login=args.force,
        interactive=args.headed,
        site_override=args.site,
    )
    site = provider.site
    target = PageTarget(
        page_id="auth-validation",
        url=VALIDATION_URLS[site],
        source="web",
        product=None,
        device="desktop",
        locale="zh-CN" if site == "cn" else "en-US",
    )
    session = await provider.prepare(target, AuthMode.REQUIRED)
    print(json.dumps(session.summary.model_dump(mode="json"), ensure_ascii=False))
    return 0 if session.storage_state else 2


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "page":
        return asyncio.run(_run_page(args))
    if args.command == "auth" and args.auth_command == "login":
        return asyncio.run(_run_auth_login(args))
    return 2
