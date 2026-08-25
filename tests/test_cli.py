from portal_audit.interfaces.cli import build_parser, requested_variants


def test_page_cli_defaults_to_full_device_locale_matrix():
    args = build_parser().parse_args(["page", "--url", "https://example.test"])

    assert args.device is None
    assert args.locale is None
    assert requested_variants(args.device, args.locale) == [
        ("desktop", "zh-CN"),
        ("desktop", "en-US"),
        ("mobile", "zh-CN"),
        ("mobile", "en-US"),
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

    assert requested_variants(args.device, args.locale) == [("mobile", "en-US")]


def test_page_cli_can_restrict_only_one_matrix_dimension():
    assert requested_variants("desktop", None) == [
        ("desktop", "zh-CN"),
        ("desktop", "en-US"),
    ]
    assert requested_variants(None, "zh-CN") == [
        ("desktop", "zh-CN"),
        ("mobile", "zh-CN"),
    ]
