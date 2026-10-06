import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'summarize-roommate-board-samples.py'
SPEC = importlib.util.spec_from_file_location('samples', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        fields = 'runId profile agent process thread iteration inputIndex startedAtEpochMs elapsedMs httpStatus success failure responseBytes'.split()
        with (self.directory / 'a0-p0-t0.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for i in range(100):
                writer.writerow(dict(zip(fields, ['test', 'search', 0, 0, 0, i, 0,
                    1000 + i * 100, i + 1, 200, 'true', '', 100])))
        (self.directory / 'a0-p0-manifest.json').write_text(json.dumps({
            'runId': 'test', 'profileId': 'search', 'configSha256': 'hash',
            'baseUrl': 'http://local', 'connectTimeoutMs': 5000, 'socketTimeoutMs': 5000,
            'agent': 0, 'process': 0}), encoding='utf-8')

    def test_individual_quantiles_and_complete_count(self):
        result = MODULE.summarize(self.directory, 100, 1)
        self.assertEqual(result['successP95Ms'], 95)
        self.assertEqual(result['successP99Ms'], 99)
        self.assertTrue(result['sampleComplete'])

    def test_missing_samples_are_incomplete(self):
        self.assertFalse(MODULE.summarize(self.directory, 200, 2)['sampleComplete'])

    def test_duplicate_collection_rejected(self):
        data = (self.directory / 'a0-p0-t0.csv').read_bytes()
        (self.directory / 'a0-p0-t1.csv').write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            MODULE.summarize(self.directory, 100, 1)

    def test_errors_do_not_lower_success_percentiles(self):
        path = self.directory / 'a0-p0-t0.csv'
        data = path.read_text(encoding='utf-8')
        lines = data.splitlines()
        cells = lines[-1].split(',')
        cells[8:12] = ['5000', '0', 'false', 'SocketTimeoutException']
        lines[-1] = ','.join(cells)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        result = MODULE.summarize(self.directory, 100, 1)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['successes'], 99)
        self.assertEqual(result['successP99Ms'], 99)

    def test_contract_failure_is_not_a_transport_root(self):
        path = self.directory / 'a0-p0-t0.csv'
        with path.open(encoding='utf-8') as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames + ['failureRoot']
            rows = list(reader)
        for row in rows:
            row['failureRoot'] = ''
        rows[-1].update(success='false', failure='contract_mismatch', failureRoot='PAGE_TOTAL_ELEMENTS_REQUIRED')
        rows[-2].update(success='false', failure='ExecutionException', failureRoot='SocketTimeoutException', httpStatus='0')
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        result = MODULE.summarize(self.directory, 100, 1)
        self.assertEqual(result['failures']['contract_mismatch'], 1)
        self.assertEqual(result['transportFailureRoots'], {'SocketTimeoutException': 1})


if __name__ == '__main__':
    unittest.main()
