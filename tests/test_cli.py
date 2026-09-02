from portal_audit.interfaces.cli import build_parser, requested_variants


def test_portal_defaults_to_device_matrix_in_url_language():
    args = build_parser().parse_args(
        ["page", "--url", "https://www.huaweicloud.com/product/demo.html"]
    )

    assert args.device is None
    assert args.locale is None
    assert requested_variants(args.device, args.locale, url=args.url) == [
        ("desktop", "zh-CN"),
        ("mobile", "zh-CN"),
    ]


def test_international_portal_uses_url_language_for_both_devices():
    url = "https://www.huaweicloud.com/intl/en-us/product/demo.html"

    assert requested_variants(None, None, url=url) == [
        ("desktop", "en-US"),
        ("mobile", "en-US"),
    ]


def test_console_defaults_to_desktop_locale_matrix():
    url = "https://console.huaweicloud.com/modelarts/"

    assert requested_variants(None, None, url=url) == [
        ("desktop", "zh-CN"),
        ("desktop", "en-US"),
    ]


def test_page_cli_explicit_device_and_locale_select_one_variant():
    args = build_parser().parse_args(
        [
            "page",
            "--url",
            "https://example.test",
            "--device",
            "mobile",
            "--locale",
            "en-US",
        ]
    )

    assert requested_variants(args.device, args.locale, url=args.url) == [
        ("mobile", "en-US")
    ]


def test_page_cli_can_restrict_only_one_matrix_dimension():
    assert requested_variants("desktop", None) == [
        ("desktop", "zh-CN"),
    ]
    assert requested_variants(None, "zh-CN") == [
        ("desktop", "zh-CN"),
        ("mobile", "zh-CN"),
    ]


def test_console_mobile_can_be_forced_explicitly():
    url = "https://console.huaweicloud.com/modelarts/"

    assert requested_variants("mobile", None, url=url) == [
        ("mobile", "zh-CN"),
        ("mobile", "en-US"),
    ]


def test_config_validation_command_is_available():
    args = build_parser().parse_args(["validate-config"])

    assert args.command == "validate-config"
