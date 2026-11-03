import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SampleModelTests(unittest.TestCase):
    def test_adventureworks_is_the_only_external_source(self):
        sources = json.loads((ROOT / 'Base/DataSources.json').read_text())['dataSources']
        self.assertEqual([s['name'] for s in sources], ['AdventureWorks'])

    def test_all_entity_references_resolve_inside_the_small_model(self):
        entities = [json.loads(p.read_text()) for p in (ROOT / 'Model').rglob('*.json') if p.name != '.properties.json']
        identifiers = {e['id'] for e in entities}
        for entity in entities:
            for source in entity.get('sources', []):
                if 'dataSource' in source:
                    self.assertEqual(source['dataSource'], 'AdventureWorks')
                else:
                    self.assertIn(source['sourceLocation'], identifiers)
            for relation in entity.get('relationships', []):
                self.assertIn(relation['targetLocation'], identifiers)

    def test_customer_uses_the_standard_table_without_custom_views(self):
        path = ROOT / 'Model/010-Stage/AdventureWorks/SalesLT/Customer.json'
        sources = json.loads(path.read_text())['sources']
        self.assertEqual(len(sources), 1)
        self.assertIn('[SalesLT].[Customer]', sources[0]['sourceLocation'])
        self.assertNotIn('Customer_EN', sources[0]['sourceLocation'])
        self.assertNotIn('Customer_DE', sources[0]['sourceLocation'])

    def test_only_classic_powerbi_and_docs_are_registered(self):
        descriptor = json.loads((ROOT / 'ORAYLISDatabricksSample.dm8s').read_text())
        self.assertEqual({t['name'] for t in descriptor['generatorTargets']}, {'databricks', 'powerbi', 'docs'})
