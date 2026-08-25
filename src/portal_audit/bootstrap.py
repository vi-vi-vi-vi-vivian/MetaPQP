"""Composition root for the local modular monolith."""

from __future__ import annotations

from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
from portal_audit.adapters.auth.config import YamlAccountCredentialSource
from portal_audit.adapters.auth.huaweicloud import HuaweiCloudAuthProvider
from portal_audit.adapters.browser.playwright_browser import PlaywrightBrowser
from portal_audit.adapters.models.openrouter import OpenRouterModelAdapter
from portal_audit.adapters.openjiuwen.workflow_runner import OpenJiuwenWorkflowRunner
from portal_audit.adapters.persistence.sqlite import SQLiteAuditJobRepository
from portal_audit.application.services.assessment_builder import AssessmentBuilder
from portal_audit.application.services.baseline_collector import BaselineCollector
from portal_audit.application.services.check_executor import CheckExecutor
from portal_audit.application.services.check_plan_builder import CheckPlanBuilder
from portal_audit.application.services.page_context_resolver import PageContextResolver
from portal_audit.application.use_cases.run_page_audit import PageAuditPipeline
from portal_audit.capabilities.checkers.page import (
    BrokenLinksChecker,
    DocumentStructureChecker,
    ImageAltChecker,
    MobileHorizontalOverflowChecker,
    MobileTapTargetChecker,
    PageLoadChecker,
    RuntimeErrorsChecker,
)
from portal_audit.capabilities.context_detectors.detectors import (
    CommerceFeatureDetector,
    JourneyStageDetector,
    PageArchetypeDetector,
)
from portal_audit.domain.registry import CheckSpecRegistry, StandardsRegistry
from portal_audit.interfaces.reporting.output_writer import OutputWriter
from portal_audit.settings import Settings
from portal_audit.skill_runtime.batch_executor import BatchModelSkillExecutor
from portal_audit.skill_runtime.executor import ModelSkillExecutor
from portal_audit.skill_runtime.loader import SkillLoader


def _configure_openjiuwen_logging(settings: Settings) -> None:
    from openjiuwen.core.common.logging.log_config import log_config
    from openjiuwen.core.common.logging.manager import LogManager

    outputs = ["console", "file"] if settings.openjiuwen_console_logs else ["file"]
    log_config.load_from_dict(
        {
            "backend": "default",
            "level": settings.openjiuwen_log_level,
            "log_path": str(settings.project_root / "logs"),
            "output": outputs,
            "interface_output": outputs,
            "performance_output": outputs,
        }
    )
    LogManager.reset()


def build_auth_provider(
    settings: Settings,
    *,
    force_login: bool = False,
    interactive: bool = False,
    headless: bool | None = None,
    site_override: str | None = None,
) -> HuaweiCloudAuthProvider:
    account = YamlAccountCredentialSource(settings.auth_account_config_path).load()
    if account.provider != "huaweicloud":
        raise ValueError(f"Unsupported auth provider: {account.provider}")
    return HuaweiCloudAuthProvider(
        username=account.username,
        password=account.password,
        account_id=account.account_id,
        account_type=account.account_type,
        enabled=account.enabled,
        state_path=settings.data_root / "auth" / f"{account.account_id}.json",
        site=site_override or account.site,
        timeout_ms=settings.huaweicloud_auth_timeout_ms,
        headless=settings.huaweicloud_login_headless if headless is None else headless,
        force_login=force_login,
        interactive=interactive,
    )


def build_page_audit_runner(settings: Settings | None = None) -> OpenJiuwenWorkflowRunner:
    settings = settings or Settings()
    _configure_openjiuwen_logging(settings)
    store = LocalArtifactStore(settings.output_root)
    browser = PlaywrightBrowser(
        store,
        headless=settings.browser_headless,
        timeout_ms=settings.browser_timeout_ms,
    )
    auth_provider = build_auth_provider(settings)
    model = OpenRouterModelAdapter(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key.get_secret_value()
        if settings.openrouter_api_key
        else None,
        model=settings.openrouter_model,
    )
    standards = StandardsRegistry(settings.config_root / "standards").load()
    registry = CheckSpecRegistry(settings.config_root / "check_specs", standards).load()
    context_resolver = PageContextResolver(
        [JourneyStageDetector(), PageArchetypeDetector(), CommerceFeatureDetector()]
    )
    plan_builder = CheckPlanBuilder(
        registry,
        settings.config_root / "audit_profiles",
        settings.config_root / "execution_policies",
    )
    skill_loader = SkillLoader(settings.skills_root)
    skill_executor = ModelSkillExecutor(skill_loader, model)
    batch_skill_executor = BatchModelSkillExecutor(skill_loader, model)
    checkers = {
        "page-load-checker": PageLoadChecker(),
        "document-structure-checker": DocumentStructureChecker(),
        "runtime-errors-checker": RuntimeErrorsChecker(),
        "broken-links-checker": BrokenLinksChecker(settings.browser_max_links),
        "image-alt-checker": ImageAltChecker(),
        "mobile-horizontal-overflow-checker": MobileHorizontalOverflowChecker(),
        "mobile-tap-target-checker": MobileTapTargetChecker(),
    }
    executor = CheckExecutor(registry, checkers, skill_executor, batch_skill_executor)
    output_writer = OutputWriter(
        settings.output_root,
        model_name=settings.openrouter_model,
        model_enabled=model.enabled,
        standards=standards,
    )
    pipeline = PageAuditPipeline(
        baseline=BaselineCollector(browser, auth_provider),
        context_resolver=context_resolver,
        plan_builder=plan_builder,
        check_executor=executor,
        assessment_builder=AssessmentBuilder(registry),
        output_writer=output_writer,
    )
    repository = SQLiteAuditJobRepository(settings.data_root / "app.db")
    return OpenJiuwenWorkflowRunner(
        pipeline,
        repository,
        timeout_seconds=settings.workflow_timeout_seconds,
    )
