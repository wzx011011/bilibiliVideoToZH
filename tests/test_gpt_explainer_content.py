import json
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / 'src/gpt_explainer/content.json'


def test_every_chapter_has_sources_and_narration():
    data = json.loads(CONTENT.read_text(encoding='utf-8'))
    sources = {s['id'] for s in data['sources']}
    assert data['as_of'] == '2026-09-06'
    assert len(data['chapters']) == 12
    assert all(s['url'].startswith('https://') for s in data['sources'])
    for chapter in data['chapters']:
        assert chapter['narration'].strip()
        assert chapter['source_ids'] and set(chapter['source_ids']) <= sources
        for bar in chapter.get('bars', []):
            assert 0 <= bar['value'] <= bar['max']
            assert bar['display']


def test_index_versions_not_combined():
    data = json.loads(CONTENT.read_text(encoding='utf-8'))
    assert [b['value'] for b in data['chapters'][2]['bars']] == [48, 53, 55]
    assert 'v4.2' in data['chapters'][2]['notes'][0]
    assert sum(b['value'] for b in data['chapters'][3]['bars']) == 100
    assert 'v4.1.1' in data['chapters'][4]['notes'][0]
    assert 'v4.2' in data['chapters'][4]['notes'][1]


def test_price_example_is_reproducible():
    data = json.loads(CONTENT.read_text(encoding='utf-8'))
    bars = data['chapters'][8]['bars']
    assert bars[0]['value'] == 100000 / 1000000 * 10
    assert bars[1]['value'] == 10000 / 1000000 * 50
    assert sum(b['value'] for b in bars) == 1.5
