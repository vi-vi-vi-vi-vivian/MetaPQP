"""Composition root for the local modular monolith."""

from __future__ import annotations

from portal_audit.adapters.artifacts.local_store import LocalArtifactStore
from portal_audit.adapters.auth.config import YamlAccountCredentialSource
from portal_audit.adapters.auth.huaweicloud import HuaweiCloudAuthProvider
from portal_audit.adapters.browser.playwright_browser import PlaywrightBrowser
from portal_audit.adapters.browser.playwright_journey import PlaywrightJourneySession
from portal_audit.adapters.models.gemini import GeminiModelAdapter
from portal_audit.adapters.models.openrouter import OpenRouterModelAdapter
from portal_audit.adapters.network.proxy import resolve_https_proxy
from portal_audit.adapters.openjiuwen.workflow_runner import OpenJiuwenWorkflowRunner
from portal_audit.adapters.persistence.sqlite import SQLiteAuditJobRepository
from portal_audit.application.services.assessment_builder import AssessmentBuilder
from portal_audit.application.services.baseline_collector import BaselineCollector
from portal_audit.application.services.check_executor import CheckExecutor
from portal_audit.application.services.check_plan_builder import CheckPlanBuilder
from portal_audit.application.services.journey_checks import (
    JourneyAssessmentBuilder,
    JourneyCheckExecutor,
    JourneyCheckPlanBuilder,
    JourneyEvidenceBuilder,
)
from portal_audit.application.services.page_context_resolver import PageContextResolver
from portal_audit.application.services.page_map_resolver import PageMapNodeResolver
from portal_audit.application.services.transition_checks import (
    TransitionCheckExecutor,
    TransitionCheckPlanBuilder,
)
from portal_audit.application.use_cases.run_journey_audit import JourneyAuditRunner
from portal_audit.application.use_cases.run_page_audit import PageAuditPipeline
from portal_audit.capabilities.context_detectors.detectors import (
    CommerceFeatureDetector,
    JourneyStageDetector,
    PageArchetypeDetector,
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
from portal_audit.interfaces.reporting.journey_output_writer import JourneyOutputWriter
from portal_audit.interfaces.reporting.output_writer import OutputWriter
from portal_audit.settings import Settings
from portal_audit.skill_runtime.batch_executor import BatchModelSkillExecutor
from portal_audit.skill_runtime.executor import ModelSkillExecutor
from portal_audit.skill_runtime.loader import SkillLoader
from portal_audit.skill_runtime.visual_executor import VisualBatchSkillExecutor


def _secret(value):
    return value.get_secret_value() if value else None


def _build_model(settings: Settings, profile: str):
    """Build a provider-neutral text or vision model profile from environment settings."""
    model_proxy = resolve_https_proxy(settings.model_https_proxy)
    is_vision = profile == settings.visual_model_profile
    provider = (
        settings.vision_model_provider if is_vision else settings.text_model_provider
    ).strip().lower()
    if provider == "gemini":
        return GeminiModelAdapter(
            api_key=_secret(settings.vision_model_api_key)
            or _secret(settings.gemini_api_key),
            model=settings.vision_model_name or settings.gemini_model,
            timeout=settings.gemini_timeout_seconds,
            max_images=settings.visual_model_max_images_per_call if is_vision else 0,
            proxy_url=model_proxy,
            fallback_models=[
                item.strip()
                for item in settings.gemini_fallback_models.split(",")
                if item.strip()
            ],
            retry_attempts=settings.model_retry_attempts,
            retry_backoff_seconds=settings.model_retry_backoff_seconds,
            fallback_probe_timeout=settings.gemini_fallback_probe_timeout_seconds,
            image_compress_threshold_bytes=settings.gemini_image_compress_threshold_bytes,
            image_max_pixels=settings.gemini_image_max_pixels,
            image_jpeg_quality=settings.gemini_image_jpeg_quality,
        )
    if provider in {"openrouter", "openai-compatible", "openai_compatible"}:
        return OpenRouterModelAdapter(
            base_url=(
                settings.vision_model_base_url if is_vision else settings.text_model_base_url
            )
            or settings.openrouter_base_url,
            api_key=(
                _secret(settings.vision_model_api_key)
                if is_vision
                else _secret(settings.text_model_api_key)
            )
            or _secret(settings.openrouter_api_key),
            model=(settings.vision_model_name if is_vision else settings.text_model_name)
            or settings.openrouter_model,
            proxy_url=model_proxy,
            retry_attempts=settings.model_retry_attempts,
            retry_backoff_seconds=settings.model_retry_backoff_seconds,
            provider_name=provider.replace("_", "-"),
            max_images=settings.visual_model_max_images_per_call if is_vision else None,
        )
    raise ValueError(f"Unsupported model provider for {profile}: {provider}")


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
        visual_audit_enabled=settings.visual_audit_enabled,
    )
    auth_provider = build_auth_provider(settings)
    model = _build_model(settings, settings.text_model_profile)
    visual_model = _build_model(settings, settings.visual_model_profile)
    standards = StandardsRegistry(settings.config_root / "standards").load()
    capabilities = CapabilityRegistry(settings.config_root / "capabilities").load()
    registry = CheckSpecRegistry(
        settings.config_root / "check_specs", standards, capabilities
    ).load()
    context_resolver = PageContextResolver(
        [JourneyStageDetector(), PageArchetypeDetector(), CommerceFeatureDetector()]
    )
    plan_builder = CheckPlanBuilder(
        registry,
        settings.config_root / "audit_profiles",
        settings.config_root / "execution_policies",
        visual_audit_enabled=settings.visual_audit_enabled,
        capabilities=capabilities,
    )
    skill_loader = SkillLoader(settings.skills_root, capabilities)
    skill_executor = ModelSkillExecutor(skill_loader, model)
    batch_skill_executor = BatchModelSkillExecutor(skill_loader, model)
    visual_skill_executor = VisualBatchSkillExecutor(skill_loader, visual_model)
    checkers = {
        item.id: capabilities.create_checker(item.id, settings)
        for item in capabilities.all()
        if item.kind.value == "deterministic" and "page" in [scope.value for scope in item.supported_scopes]
    }
    executor = CheckExecutor(
        registry,
        checkers,
        skill_executor,
        batch_skill_executor,
        visual_skill_executor,
    )
    output_writer = OutputWriter(
        settings.output_root,
        model_name=model.model,
        model_enabled=model.enabled,
        visual_model_name=visual_model.model,
        visual_model_enabled=visual_model.enabled,
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


def build_journey_audit_runner(settings: Settings | None = None) -> JourneyAuditRunner:
    settings = settings or Settings()
    page_runner = build_page_audit_runner(settings)
    store = LocalArtifactStore(settings.output_root)
    standards = StandardsRegistry(settings.config_root / "standards").load()
    capabilities = CapabilityRegistry(settings.config_root / "capabilities").load()
    check_specs = CheckSpecRegistry(
        settings.config_root / "check_specs", standards, capabilities
    ).load()
    page_maps = PageMapRegistry(settings.config_root / "page_maps").load()
    transitions = TransitionRegistry(settings.config_root / "transitions", page_maps).load()
    journeys = JourneyRegistry(
        settings.config_root / "journeys",
        page_maps,
        transitions,
    ).load()
    safety_profiles = SafetyProfileRegistry(
        settings.config_root / "safety_profiles"
    ).load()
    resolver = PageMapNodeResolver(page_maps)
    auth_provider = build_auth_provider(settings)
    # Journey checks are text-only and therefore deliberately use the text profile.
    journey_model = _build_model(settings, settings.text_model_profile)
    return JourneyAuditRunner(
        page_pipeline=page_runner.pipeline,
        page_maps=page_maps,
        transitions=transitions,
        journeys=journeys,
        safety_profiles=safety_profiles,
        resolver=resolver,
        auth_provider=auth_provider,
        browser_factory=lambda headless: PlaywrightJourneySession(
            store,
            resolver,
            headless=headless,
            timeout_ms=settings.browser_timeout_ms,
        ),
        transition_plan_builder=TransitionCheckPlanBuilder(
            check_specs,
            settings.config_root / "audit_profiles",
        ),
        transition_executor=TransitionCheckExecutor(
            check_specs,
            {
                item.id: capabilities.create_checker(item.id, settings)
                for item in capabilities.all()
                if item.kind.value == "deterministic"
                and "transition" in [scope.value for scope in item.supported_scopes]
            },
        ),
        journey_evidence_builder=JourneyEvidenceBuilder(),
        journey_plan_builder=JourneyCheckPlanBuilder(
            check_specs,
            settings.config_root / "audit_profiles",
        ),
        journey_executor=JourneyCheckExecutor(
            check_specs,
            journey_model,
            SkillLoader(settings.skills_root, capabilities),
        ),
        journey_assessment_builder=JourneyAssessmentBuilder(),
        output_writer=JourneyOutputWriter(
            settings.output_root,
            check_specs=check_specs,
            standards=standards,
        ),
        journey_executors=JourneyExecutorRegistry(
            settings.config_root / "journey_executors"
        ).load(),
    )
