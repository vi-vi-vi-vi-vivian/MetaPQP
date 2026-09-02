from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_cloud_product_lifecycle_defines_seven_ordered_stages():
    template = yaml.safe_load(
        (ROOT / "config/journey_templates/cloud-product-lifecycle.yaml").read_text()
    )

    assert [stage["id"] for stage in template["stages"]] == [
        "awareness",
        "purchase",
        "order",
        "payment",
        "usage",
        "renewal",
        "unsubscribe",
    ]


def test_tokenplan_scenario_declares_surface_specific_matrix():
    scenario = yaml.safe_load(
        (ROOT / "config/scenarios/tokenplan-normal-to-payment.yaml").read_text()
    )

    assert scenario["auth"]["mode"] == "required"
    assert scenario["execution_matrix"] == {
        "source": "web",
        "by_page_surface": {
            "portal": {
                "devices": ["desktop", "mobile"],
                "locale_strategy": "url",
            },
            "console": {
                "devices": ["desktop"],
                "locales": ["zh-CN", "en-US"],
            },
        },
    }


def test_tokenplan_binding_declares_page_surfaces():
    binding = yaml.safe_load(
        (ROOT / "config/product_journey_bindings/token-plan.yaml").read_text()
    )

    assert [page["page_surface"] for page in binding["pages"][:2]] == [
        "portal",
        "console",
    ]
