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


def test_tokenplan_scenario_declares_device_and_locale_matrix():
    scenario = yaml.safe_load(
        (ROOT / "config/scenarios/tokenplan-normal-to-payment.yaml").read_text()
    )

    assert scenario["auth"]["mode"] == "required"
    assert scenario["execution_matrix"] == {
        "source": "web",
        "devices": ["desktop", "mobile"],
        "locales": ["zh-CN", "en-US"],
    }
