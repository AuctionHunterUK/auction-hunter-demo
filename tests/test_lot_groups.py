"""Offline generator checks: python3 -m unittest discover -s tests."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
os.environ['REPO_DIR'] = str(ROOT / 'finds')
spec = importlib.util.spec_from_file_location('scraper', ROOT / 'finds/scrape_auction_finds_map.py')
scraper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scraper)


class LotGroupsTest(unittest.TestCase):
    def test_generated_page_matches_checked_in_ui(self):
        generated = BeautifulSoup(scraper.build_html([], []), 'html.parser')
        checked_in = BeautifulSoup((ROOT / 'finds/index.html').read_bytes(), 'html.parser')
        self.assertEqual(generated.find('style').string, checked_in.find('style').string)
        # Embedded catalogue/map data legitimately differ; behavior after them must match.
        marker = '// ── LOT IMAGE LOADING / FAILURE STATES ──'
        self.assertEqual(str(generated).split(marker)[1].split('// ── DESKTOP-ONLY MINI-MAP')[0], str(checked_in).split(marker)[1].split('// ── DESKTOP-ONLY MINI-MAP')[0])
        self.assertEqual([b['data-target'] for b in generated.select('.group-tab')], ['local', 'today', 'uk-wide'])
        self.assertEqual([s['id'] for s in generated.select('#cards-area section:not([hidden])')], ['local'])

    def test_house_classification_is_preserved(self):
        self.assertTrue(scraper.is_local('Bourne End Auction Rooms Ltd'))
        self.assertFalse(scraper.is_local('Other auction house'))

    def test_images_are_deferred_even_for_priority_and_empty_sections_hide(self):
        lot = dict(id='test', url='https://example.com/lot', title='Pine table', house='Other', img_file='test.jpg')
        with patch.object(scraper, 'is_valid_image_file', return_value=True):
            card = BeautifulSoup(scraper._card_html(lot, False, ({}, {}), True), 'html.parser')
        self.assertNotIn('src', card.img.attrs)
        self.assertEqual(card.img['data-src'], 'images/test.jpg')
        for group in ['local', 'today', 'uk-wide']:
            section = BeautifulSoup(scraper._section_html('Lots', [], group, set(), ({}, {})), 'html.parser').section
            self.assertEqual(section.has_attr('hidden'), group != 'local')


if __name__ == '__main__':
    unittest.main()
