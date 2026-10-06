import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'prepare-ngrinder-ui.py'
SPEC = importlib.util.spec_from_file_location('prepare_ui', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ValidationTests(unittest.TestCase):
    def classify(self, log):
        return MODULE.classify_validation('test.groovy', log)

    def test_success_requires_one_request_and_no_error(self):
        self.assertTrue(self.classify('Totals 1 0 1000')['passed'])
        self.assertFalse(self.classify('Totals 0 0')['passed'])
        self.assertFalse(self.classify('Totals 2 0')['passed'])
        self.assertFalse(self.classify('Totals 1 0\nERROR afterProcess failed')['passed'])

    def test_missing_totals_is_collection_failure(self):
        result = self.classify('INFO Starting\nINFO Finished\nPicked up JAVA_TOOL_OPTIONS')
        self.assertEqual(result['outcome'], 'RESULT_COLLECTION_FAILED')
        self.assertIsNone(result['errors'])
        self.assertIsNone(result['successes'])

    def test_initialization_error_is_setup_failure(self):
        self.assertEqual(self.classify('ERROR beforeProcess\nCaused by: FileNotFoundException')['outcome'], 'SETUP_FAILED')

    def test_initialization_failure_with_totals_is_still_setup_failure(self):
        self.assertEqual(self.classify('ERROR beforeThread failed\nTotals 0 0')['outcome'], 'SETUP_FAILED')

    def test_request_failures_have_separate_categories(self):
        cases = {
            'HTTP_REQUEST_FAILED': 'http_401 (HTTP 401)',
            'TRANSPORT_FAILED': 'ExecutionException/SocketTimeoutException (HTTP 0)',
            'CONTRACT_MISMATCH': 'contract_mismatch/PAGE_TOTAL_ELEMENTS_REQUIRED (HTTP 200)',
        }
        for category, diagnostic in cases.items():
            with self.subTest(category=category):
                row = self.classify('ERROR ' + category + ': ' + diagnostic + '\nTotals 0 1')
                self.assertEqual(row['outcome'], category)
                self.assertEqual(row['message'], diagnostic)
        self.assertEqual(self.classify('Totals 0 1')['outcome'], 'REQUEST_FAILED')

    def test_unknown_exception_detail_is_not_printed(self):
        row = self.classify('ERROR CONTRACT_MISMATCH: secret body and token\nTotals 0 1')
        self.assertNotIn('secret', row['message'])

    def test_correlated_process_log_fallback(self):
        log = 'INFO ui-validation-one\nTotals 1 0'
        actual, source = MODULE.resolve_validation_log('stderr only', 'ui-validation-one', lambda: log)
        self.assertEqual(actual, log)
        self.assertEqual(source, 'controller-process-log')

    def test_unrelated_process_log_is_never_accepted(self):
        actual, source = MODULE.resolve_validation_log('stderr only', 'ui-validation-one',
            lambda: 'INFO ui-validation-other\nTotals 1 0', pause=lambda delay: None)
        self.assertEqual(actual, 'stderr only')
        self.assertEqual(source, 'api')
        self.assertEqual(self.classify(actual)['outcome'], 'RESULT_COLLECTION_FAILED')

    def test_unavailable_process_log_remains_unconfirmed(self):
        def missing():
            raise RuntimeError('missing file')
        actual, _ = MODULE.resolve_validation_log('stderr only', 'ui-validation-one', missing, pause=lambda delay: None)
        self.assertEqual(self.classify(actual)['outcome'], 'RESULT_COLLECTION_FAILED')

    def test_complete_api_log_needs_no_fallback(self):
        def unused():
            self.fail('Must not read the shared log when API results are complete')
        self.assertEqual(MODULE.resolve_validation_log('Totals 1 0', 'ui-validation-one', unused), ('Totals 1 0', 'api'))

    def test_marker_is_injected_only_in_validation_copy(self):
        content = 'class Test { static void beforeProcess() {\n loadSettings()\n} }'
        marked = MODULE.validation_content(content, 'ui-validation-one')
        self.assertNotIn('ui-validation-one', content)
        self.assertIn("grinder.logger.info('ui-validation-one')", marked)
        with self.assertRaises(RuntimeError):
            MODULE.validation_content('no entry point', 'ui-validation-one')


if __name__ == '__main__':
    unittest.main()
