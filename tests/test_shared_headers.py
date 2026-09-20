"""Shared chrome contract; run alongside the lot generator checks."""
from pathlib import Path
import unittest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['houses/index.html', 'finds/index.html', 'about.html', 'settings/index.html', 'proposal.html']

class SharedHeaderTest(unittest.TestCase):
    def test_all_pages_use_shared_assets_and_controls(self):
        for name in PAGES:
            with self.subTest(page=name):
                soup = BeautifulSoup((ROOT / name).read_bytes(), 'html.parser')
                header = soup.select_one('body > .as-header')
                self.assertIsNotNone(header)
                self.assertEqual(header.select_one('.brand').get_text(strip=True), 'AuctionSavvy')
                self.assertEqual([a.get_text(strip=True) for a in header.select('.app-nav a')], ['Map', 'Lots'])
                self.assertEqual([a.get_text(strip=True) for a in header.select('.as-utilities a')], ['About', 'Edit', 'Private Proposal'])
                css = soup.select_one('link[href$="assets/header.css"]')
                js = soup.select_one('script[src$="assets/header.js"]')
                self.assertTrue((ROOT / name).parent.joinpath(css['href']).resolve().is_file())
                self.assertTrue((ROOT / name).parent.joinpath(js['src']).resolve().is_file())

    def test_map_controls_are_keyboard_buttons(self):
        soup = BeautifulSoup((ROOT / 'houses/index.html').read_bytes(), 'html.parser')
        self.assertEqual(len(soup.select('#toolbar button[type="button"]')), 4)
        self.assertEqual(soup.select_one('.brand')['onclick'], 'goHome()')

    def test_both_proposal_views_keep_one_site_header(self):
        soup = BeautifulSoup((ROOT / 'proposal.html').read_bytes(), 'html.parser')
        self.assertEqual(len(soup.select('body > .as-header')), 1)
        self.assertIsNotNone(soup.select_one('#proposal-overview-view'))
        self.assertIsNotNone(soup.select_one('#proposal-text-view'))
        self.assertEqual(len(soup.select('[data-view-target]')), 2)

if __name__ == '__main__':
    unittest.main()
