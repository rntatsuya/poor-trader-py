import unittest
import shutil
import os

from poor_trader.screening import indicator
from poor_trader import market, config
from poor_trader.screening.indicator import PickleIndicatorFactory, IndicatorRunnerFactory, PickleIndicatorRunnerFactory

TEMP_INDICATORS_PATH = config.TEST_TEMP_PATH / 'indicators'

HISTORICAL_DATA_PATH = config.TEST_RESOURCES_PATH / 'historical_data.csv'
INTRADAY_HISTORICAL_DATA_PATH = config.TEST_RESOURCES_PATH / 'intraday_historical_data.csv'


class TestIndicator(unittest.TestCase):
    def setUp(self):
        self.market = market.csv_to_market('TestMarket', HISTORICAL_DATA_PATH)

    def tearDown(self):
        if os.path.exists(config.TEST_TEMP_PATH):
            shutil.rmtree(config.TEST_TEMP_PATH)

    def test_pickle_indicato_factory(self):
        runner = indicator.ATRChannel(top=2, bottom=1, sma=2)
        factory = PickleIndicatorFactory(TEMP_INDICATORS_PATH, self.market)
        atr_channel_indicator = factory.create(indicator.ATRChannel, top=runner.top, bottom=runner.bottom, sma=runner.sma)
        symbols = self.market.get_symbols()
        self.assertTrue(len(symbols) > 0)
        for symbol in symbols:
            expected_path = (factory.dir_path / runner.unique_name) / '{}.{}'.format(symbol, config.PICKLE_EXTENSION)
            self.assertTrue(os.path.exists(expected_path))
        self.assertTrue(len(atr_channel_indicator.attributes) > 0, 'No attributes created.')
        attribute_keys = atr_channel_indicator.attributes.keys()
        self.assertTrue('Top' in attribute_keys)
        self.assertTrue('Mid' in attribute_keys)
        self.assertTrue('Bottom' in attribute_keys)

    def test_indicator_runner_factory(self):
        factory = IndicatorRunnerFactory()
        ema = factory.create(indicator.EMA, period=2)
        symbol = self.market.get_symbols()[0]
        df_ema = ema.run(symbol, self.market.get_quotes(symbol=symbol))
        self.assertEqual(' '.join(['EMA', 'Direction']), ' '.join(df_ema.columns))

    def test_pickle_indicator_runner_factory(self):
        factory = PickleIndicatorRunnerFactory(TEMP_INDICATORS_PATH)
        ema = factory.create(indicator.EMA, period=2)
        self.assertTrue(len(self.market.get_symbols()) > 0)
        for symbol in self.market.get_symbols():
            expected_pickle_path = (TEMP_INDICATORS_PATH / ema.unique_name) / '{}.{}'.format(symbol, config.PICKLE_EXTENSION)
            expected_sub_pickle_path = (TEMP_INDICATORS_PATH / ema.unique_name.replace('ema', 'sma')) / '{}.{}'.format(symbol, config.PICKLE_EXTENSION)
            self.assertFalse(os.path.exists(expected_pickle_path))
            self.assertFalse(os.path.exists(expected_sub_pickle_path))
            ema.run(symbol, self.market.get_quotes(symbol=symbol))
            self.assertTrue(os.path.exists(expected_pickle_path))
            self.assertTrue(os.path.exists(expected_sub_pickle_path))


class TestIndicatorRunner(unittest.TestCase):
    def setUp(self):
        self.market = market.csv_to_market('TestMarket', INTRADAY_HISTORICAL_DATA_PATH)

    def tearDown(self):
        if os.path.exists(config.TEST_TEMP_PATH):
            shutil.rmtree(config.TEST_TEMP_PATH)

    def test_indicator_runners(self):
        factory = PickleIndicatorFactory(TEMP_INDICATORS_PATH, self.market)
        runner_classes = indicator.IndicatorRunner.__subclasses__()
        self.assertTrue(len(runner_classes) > 0)
        for runner_class in runner_classes:
            _indicator = factory.create(runner_class)
            expected_dir_path = TEMP_INDICATORS_PATH /_indicator.name
            self.assertTrue(os.path.exists(expected_dir_path))
            self.assertIsNotNone(_indicator.get_attribute('Direction'), msg=runner_class.__name__)


if __name__ == '__main__':
    unittest.main()