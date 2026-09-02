"""Local CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
from itertools import product

from portal_audit.adapters.auth.huaweicloud import VALIDATION_URLS
from portal_audit.application.services.page_surface import (
    portal_locale_from_url,
    resolve_page_surface,
)
from portal_audit.bootstrap import (
    build_auth_provider,
    build_journey_audit_runner,
    build_page_audit_runner,
)
from portal_audit.domain.models import (
    AuthMode,
    JourneyAuditRequest,
    ModelExecutionMode,
    PageAuditRequest,
    PageSurface,
    PageTarget,
)
from portal_audit.domain.registry import (
    CapabilityRegistry,
    CheckSpecRegistry,
    JourneyExecutorRegistry,
    JourneyRegistry,
    PageMapRegistry,
    SafetyProfileRegistry,
    StandardsRegistry,
    TransitionRegistry,
)
from portal_audit.settings import Settings
from portal_audit.skill_runtime.loader import SkillLoader

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
        "--page-surface",
        choices=[item.value for item in PageSurface],
        help="override URL-based surface detection (portal or console)",
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
    audit = subparsers.add_parser("audit", help="run an explicitly selected audit scope")
    audit.add_argument("--scope", choices=["journey"], required=True)
    audit.add_argument("--journey", required=True)
    audit.add_argument("--url", help="optional start URL override")
    audit.add_argument("--product")
    audit.add_argument("--device", choices=["desktop"], default="desktop")
    audit.add_argument("--locale", choices=DEFAULT_LOCALES, default="zh-CN")
    audit.add_argument("--auth", choices=[item.value for item in AuthMode], default="required")
    audit.add_argument("--headless", action="store_true")
    audit.add_argument(
        "--model-execution",
        choices=[item.value for item in ModelExecutionMode],
        default=ModelExecutionMode.GROUPED.value,
    )
    subparsers.add_parser("validate-config", help="validate all declarative registries")
    return parser


async def _run_page(args: argparse.Namespace) -> int:
    runner = build_page_audit_runner()
    results = []
    page_surface = resolve_page_surface(args.url, args.page_surface)
    for device, locale in requested_variants(
        args.device,
        args.locale,
        url=args.url,
        page_surface=page_surface,
    ):
        result = await runner.run(
            PageAuditRequest(
                url=args.url,
                product=args.product,
                page_id=args.page_id,
                page_surface=page_surface,
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
                "page_surface": page_surface.value,
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
    *,
    url: str = "",
    page_surface: PageSurface | str | None = None,
) -> list[tuple[str, str]]:
    surface = resolve_page_surface(url, page_surface)
    if surface == PageSurface.CONSOLE:
        devices = (device,) if device else ("desktop",)
        locales = (locale,) if locale else DEFAULT_LOCALES
    else:
        devices = (device,) if device else DEFAULT_DEVICES
        locales = (locale or portal_locale_from_url(url),)
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
        page_surface=PageSurface.CONSOLE,
        device="desktop",
        locale="zh-CN" if site == "cn" else "en-US",
    )
    session = await provider.prepare(target, AuthMode.REQUIRED)
    print(json.dumps(session.summary.model_dump(mode="json"), ensure_ascii=False))
    return 0 if session.storage_state else 2


async def _run_audit(args: argparse.Namespace) -> int:
    if args.scope != "journey":
        raise ValueError(f"Unsupported audit scope: {args.scope}")
    result = await build_journey_audit_runner().run(
        JourneyAuditRequest(
            journey_id=args.journey,
            url=args.url,
            product=args.product,
            device=args.device,
            locale=args.locale,
            auth_mode=args.auth,
            model_execution_mode=args.model_execution,
            supervised=True,
            headless=args.headless,
        )
    )
    print(
        json.dumps(
            {
                "scope": "journey",
                "journey_id": result.journey.id,
                "job_id": result.job_id,
                "status": result.status.value,
                "coverage_status": result.coverage_status.value,
                "termination_reason": result.termination_reason,
                "output_dir": result.output_dir,
                "page_reports": [item.output_dir for item in result.page_results],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.status.value == "completed" else 1


def _validate_config() -> int:
    """Fail fast before a browser or model provider is started."""
    settings = Settings()
    standards = StandardsRegistry(settings.config_root / "standards").load()
    capabilities = CapabilityRegistry(settings.config_root / "capabilities").load()
    CheckSpecRegistry(settings.config_root / "check_specs", standards, capabilities).load()
    skill_loader = SkillLoader(settings.skills_root, capabilities)
    for capability in capabilities.all():
        if capability.kind.value == "skill":
            skill_loader.load(capability.id)
    page_maps = PageMapRegistry(settings.config_root / "page_maps").load()
    transitions = TransitionRegistry(settings.config_root / "transitions", page_maps).load()
    JourneyRegistry(settings.config_root / "journeys", page_maps, transitions).load()
    SafetyProfileRegistry(settings.config_root / "safety_profiles").load()
    JourneyExecutorRegistry(settings.config_root / "journey_executors").load()
    print("Configuration is valid.")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "page":
        return asyncio.run(_run_page(args))
    if args.command == "auth" and args.auth_command == "login":
        return asyncio.run(_run_auth_login(args))
    if args.command == "audit":
        return asyncio.run(_run_audit(args))
    if args.command == "validate-config":
        return _validate_config()
    return 2
