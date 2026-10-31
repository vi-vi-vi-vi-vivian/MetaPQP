import json
import shutil
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts.generate_capability_map import DEFAULT_REPOSITORY, load_inventory, render


class MapParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rules = []
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if 'data-rule' in attributes:
            self.rules.append(attributes['data-rule'])
        if 'id' in attributes:
            self.ids.append(attributes['id'])
        if tag == 'a':
            self.links.append(attributes.get('href', ''))


def test_six_dimensions_and_all_registered_rules_are_mapped_once():
    dimensions, inventory = load_inventory(DEFAULT_REPOSITORY)
    assert len(dimensions) == 6
    assert len(inventory) == len({item['id'] for item in inventory}) == 42
    assert Counter(item['dimension'] for item in inventory) == {'D1': 7, 'D2': 6, 'D3': 8, 'D4': 11, 'D5': 6, 'D6': 4}


def test_execution_types_and_scopes_are_disjoint_and_complete():
    document, summary = render(DEFAULT_REPOSITORY, '2026-10-31')
    assert summary['modes'] == {'code': 15, 'semantic': 18, 'vision': 3, 'reference': 6}
    assert sum(summary['modes'].values()) == summary['rules']
    assert summary['scopes'] == {'page': 19, 'transition': 8, 'journey': 9, 'comparison': 6}


def test_generated_document_contains_unique_rule_details_and_working_local_links():
    document, summary = render(DEFAULT_REPOSITORY, '2026-10-31')
    parser = MapParser()
    parser.feed(document)
    assert len(parser.rules) == len(set(parser.rules)) == 42
    assert len(parser.ids) == len(set(parser.ids))
    assert all(key in parser.ids for key in ('D1', 'D2', 'D3', 'D4', 'D5', 'D6'))
    for link in parser.links:
        if link.startswith('#'):
            assert link[1:] in parser.ids
        else:
            assert (DEFAULT_REPOSITORY / 'docs' / link).exists(), link
    assert '__MATRIX__' not in document and '__RULE_COUNT__' not in document
    assert '<script' not in document


def test_boundaries_do_not_claim_runtime_coverage_or_automatic_manual_results():
    document, summary = render(DEFAULT_REPOSITORY, '2026-10-31')
    assert '不再沿用' in document
    assert '改进机会，不直接算主体产品缺陷' in document
    assert '模型失败必须标为未执行' in document
    assert '人工走查仅提供案例证据，不算自动覆盖' in document
    assert '通用原始报告尚未全部按六维重排' in document
    assert '当前可自动覆盖约 57%' not in document


@pytest.fixture
def repository_copy(tmp_path):
    shutil.copytree(DEFAULT_REPOSITORY / 'config/check_specs', tmp_path / 'config/check_specs')
    shutil.copytree(DEFAULT_REPOSITORY / 'config/capabilities', tmp_path / 'config/capabilities')
    destination = tmp_path / 'scripts/dashboard_pipeline/assets'
    destination.mkdir(parents=True)
    shutil.copyfile(DEFAULT_REPOSITORY / 'scripts/dashboard_pipeline/assets/quality_dimensions.json', destination / 'quality_dimensions.json')
    return tmp_path


def test_new_unmapped_rule_blocks_stale_map_generation(repository_copy):
    extra = repository_copy / 'config/check_specs/new-check.yaml'
    extra.write_text('id: new-check\n')
    with pytest.raises(ValueError, match='映射不一致'):
        load_inventory(repository_copy)


def test_missing_executor_registration_blocks_generation(repository_copy):
    path = repository_copy / 'config/capabilities/deterministic/page-load-checker.yaml'
    path.unlink()
    with pytest.raises(ValueError, match='执行能力未注册'):
        load_inventory(repository_copy)


def test_duplicate_mapping_is_rejected(repository_copy):
    path = repository_copy / 'scripts/dashboard_pipeline/assets/quality_dimensions.json'
    schema = json.loads(path.read_text())
    schema['rules'].append(schema['rules'][0])
    path.write_text(json.dumps(schema))
    with pytest.raises(ValueError, match='重复检查'):
        load_inventory(repository_copy)


def test_output_is_repeatable_for_same_source_and_date():
    first, summary = render(DEFAULT_REPOSITORY, '2026-10-31')
    second, second_summary = render(DEFAULT_REPOSITORY, '2026-10-31')
    assert first == second
    assert summary == second_summary
