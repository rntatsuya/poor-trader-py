import abc
import os

import numpy as np
import pandas as pd
from path import Path

from poor_trader.market import Market
from poor_trader.screening import entity
from poor_trader import config, utils


class IndicatorRunnerFactory(object):
    __metaclass__ = abc.ABCMeta

    def create(self, cls, *args, **kwargs):
        runner = cls(*args, **kwargs)
        runner.factory = self
        return runner


class IndicatorRunner(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, name, unique_name):
        self.name = name
        self.unique_name = unique_name
        self.factory = IndicatorRunnerFactory()

    @abc.abstractmethod
    def run(self, symbol, df_quotes, df_indicator=None):
        raise NotImplementedError

    @staticmethod
    def add_direction(df, long_condition, short_condition):
        df['Direction'] = np.where(long_condition, entity.Direction.LONG,
                                   np.where(short_condition, entity.Direction.SHORT, ''))

    @staticmethod
    def is_updated(df_quotes, df_indicator):
        if df_indicator is None:
            return False
        return pd.Index.equals(df_quotes.index, df_indicator.index)


class STDEV(IndicatorRunner):
    def __init__(self, name='STDEV', period=10, field='Close'):
        super().__init__(name, 'stdev_{}_{}'.format(field, period))
        self.period = period
        self.field = field

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator
        df = pd.DataFrame(index=df_quotes.index)
        df['STDEV'] = df_quotes[self.field].rolling(self.period).std()
        self.add_direction(df, df_quotes[self.field] > df['STDEV'], df_quotes[self.field] < df['STDEV'])
        df = utils.round_df(df)
        return df


class EMA(IndicatorRunner):
    def __init__(self, name='EMA', period=10, field='Close'):
        super().__init__(name, 'ema_{}_{}'.format(field, period))
        self.period = period
        self.field = field

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator
        c = 2./(self.period + 1.)
        df = pd.DataFrame(columns=['EMA'], index=df_quotes.index)
        _sma = self.factory.create(SMA, period=self.period, field=self.field).run(symbol, df_quotes).dropna()
        if _sma.empty:
            return df
        df.loc[_sma.index.values[0], 'EMA'] = _sma.SMA.values[0]
        for i in range(1, len(df_quotes)):
            prev_ema = df.iloc[i-1]
            if pd.isnull(prev_ema.EMA): continue
            price = df_quotes.iloc[i]
            ema_value = c * price[self.field] + (1. - c) * prev_ema.EMA
            df.loc[df_quotes.index.values[i], 'EMA'] = ema_value

        self.add_direction(df, df_quotes[self.field] > df['EMA'], df_quotes[self.field] < df['EMA'])
        df = utils.round_df(df)
        return df


class SMA(IndicatorRunner):
    def __init__(self, name='SMA', period=10, field='Close'):
        super().__init__(name, 'sma_{}_{}'.format(field, period))
        self.period = period
        self.field = field

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator
        else:
            df = pd.DataFrame(index=df_quotes.index)
            df['SMA'] = df_quotes[self.field].rolling(self.period).mean()
            self.add_direction(df, df_quotes[self.field] > df['SMA'], df_quotes[self.field] < df['SMA'])
            df = utils.round_df(df)
            return df


class ATR(IndicatorRunner):
    def __init__(self, name='ATR', period=10):
        super().__init__(name, 'atr_{}'.format(period))
        self.period = period

    def true_range(self, df_quotes):
        df = pd.DataFrame(index=df_quotes.index)
        df['n_index'] = range(len(df_quotes))
        def _true_range(indices):
            _df_quotes = df_quotes.iloc[indices]
            a = utils.roundn(np.abs(_df_quotes.High - _df_quotes.Low)[-1], 4)
            b = utils.roundn(np.abs(_df_quotes.High - _df_quotes.shift(1).Close)[-1], 4)
            c = utils.roundn(np.abs(_df_quotes.Low - _df_quotes.shift(1).Close)[-1], 4)
            return max(a, b, c)
        df['true_range'] = df.n_index.rolling(2).apply(_true_range)
        return df.filter(like='true_range')

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(columns=['ATR'], index=df_quotes.index)
        df_true_range = self.true_range(df_quotes)
        for i in range(1+len(df_quotes)-self.period):
            if pd.isnull(df_true_range.iloc[i].true_range): continue
            start = i
            end = i + self.period
            last_index = end - 1
            trs = df_true_range[start:end]
            prev_atr = df.iloc[last_index-1].ATR
            if pd.isnull(prev_atr):
                atr = np.mean([tr for tr in trs.true_range.values])
            else:
                atr = (prev_atr * (self.period-1) + df_true_range.iloc[last_index].true_range) / self.period
            df.loc[df_quotes.index.values[last_index], 'ATR'] = atr
        self.add_direction(df, False, False)
        return utils.round_df(df)


class ATRChannel(IndicatorRunner):
    def __init__(self, name='ATRChannel', top=7, bottom=3, sma=150):
        super().__init__(name, 'atr_channel_{}_{}_{}'.format(top, bottom, sma))
        self.top = top
        self.bottom = bottom
        self.sma = sma

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df_top_atr = self.factory.create(ATR, period=self.top).run(symbol, df_quotes)
        df_bottom_atr = self.factory.create(ATR, period=self.bottom).run(symbol, df_quotes)
        df_sma = self.factory.create(SMA, period=self.sma).run(symbol, df_quotes)
        df = pd.DataFrame(columns=['Top', 'Mid', 'Bottom'], index=df_quotes.index)
        df['Mid'] = df_sma.SMA
        df['Top'] = df.Mid + df_top_atr.ATR
        df['Bottom'] = df.Mid - df_bottom_atr.ATR
        self.add_direction(df, df_quotes['Close'] > df['Top'], df_quotes['Close'] < df['Bottom'])
        df = utils.round_df(df)
        return df


class TrailingStops(IndicatorRunner):
    def __init__(self, name='TrailingStops', multiplier=4, period=10):
        super().__init__(name, 'trailing_stops_{}_{}'.format(multiplier, period))
        self.multiplier = multiplier
        self.period = period

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(columns=['BuyStops', 'SellStops'], index=df_quotes.index)
        df_atr = self.factory.create(ATR, period=self.period).run(symbol, df_quotes)
        sign = -1  # SellStops: -1, BuyStops: 1
        for i in range(len(df_quotes)-1):
            if pd.isnull(df_atr.iloc[i].ATR): continue
            start = i - self.period
            end = i
            quotes = df_quotes.iloc[start+1:end+1]
            cur_quote = df_quotes.iloc[i]
            next_quote = df_quotes.iloc[i + 1]
            _atr = df_atr.iloc[i].ATR

            # close_price = next_quote.Close
            # trend_dir_sign = -1 if close_price > _atr else 1

            max_price = quotes.Close.max()
            min_price = quotes.Close.min()

            sell = max_price + sign * (self.multiplier * _atr)
            buy = min_price + sign * (self.multiplier * _atr)

            sell = [sell, df.iloc[i].SellStops]
            buy = [buy, df.iloc[i].BuyStops]

            try:
                sell = np.max([x for x in sell if not pd.isnull(x)])
                buy = np.min([x for x in buy if not pd.isnull(x)])
            except:
                print(sell)

            if sign < 0:
                df.loc[df_quotes.index.values[i+1]]['SellStops'] = sell
                if next_quote.Close <= sell:
                    sign = 1
            else:
                df.loc[df_quotes.index.values[i+1]]['BuyStops'] = buy
                if next_quote.Close >= buy:
                    sign = -1

        self.add_direction(df, df_quotes.Close >= df.BuyStops, df_quotes.Close <= df.SellStops)
        df = utils.round_df(df)
        return df


class DonchianChannel(IndicatorRunner):
    def __init__(self, name='DonchianChannel', high=50, low=50):
        super().__init__(name, 'donchian_channel_{}_{}'.format(high, low))
        self.high = high
        self.low = low

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(columns=['high', 'mid', 'low'], index=df_quotes.index)
        df['High'] = df_quotes.High.rolling(window=self.high).max()
        df['Low'] = df_quotes.Low.rolling(window=self.low).min()
        df['Mid'] = (df.high + df.low)/2

        self.add_direction(df, np.logical_and(df.High.shift(1) < df.High, df.Low.shift(1) <= df.Low),
                           np.logical_and(df.Low.shift(1) > df.Low, df.High.shift(1) >= df.High))
        df = utils.round_df(df)
        return df


class MACD(IndicatorRunner):
    def __init__(self, name='MACD', fast=12, slow=26, signal=9):
        super().__init__(name, 'macd_{}_{}_{}'.format(fast, slow, signal))
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(index=df_quotes.index)
        fast_ema = self.factory.create(EMA, period=self.fast).run(symbol, df_quotes)
        slow_ema = self.factory.create(EMA, period=self.slow).run(symbol, df_quotes)
        df['MACD'] = fast_ema.EMA - slow_ema.EMA
        signal_ema = self.factory.create(EMA, period=self.signal, field='MACD').run(symbol, df)
        df['Signal'] = signal_ema.EMA
        df['MACDCrossoverSignal'] = np.where(np.logical_and(df.MACD > df.Signal, df.MACD.shift(1) <= df.Signal.shift(1)), 1, 0)
        df['SignalCrossoverMACD'] = np.where(np.logical_and(df.MACD < df.Signal, df.Signal.shift(1) <= df.MACD.shift(1)), 1, 0)
        self.add_direction(df, df['MACDCrossoverSignal'] == 1, df['SignalCrossoverMACD'] == 1)
        df = utils.round_df(df)
        return df


class MACross(IndicatorRunner):
    def __init__(self, name='MACross', fast=40, slow=60):
        super().__init__(name, 'ma_cross_{}_{}'.format(fast, slow))
        self.fast = fast
        self.slow = slow

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(index=df_quotes.index)
        fast_sma = self.factory.create(SMA, period=self.fast).run(symbol, df_quotes)
        slow_sma = self.factory.create(SMA, period=self.slow).run(symbol, df_quotes)
        df['FastSMA'] = fast_sma.SMA
        df['SlowSMA'] = slow_sma.SMA
        df['SlowCrossoverFast'] = np.where(np.logical_and(df.FastSMA <= df.SlowSMA, df.FastSMA.shift(1) > df.SlowSMA.shift(1)), 1, 0)
        df['FastCrossoverSlow'] = np.where(np.logical_and(df.FastSMA >= df.SlowSMA, df.SlowSMA.shift(1) > df.FastSMA.shift(1)), 1, 0)
        self.add_direction(df, df['FastSMA'] > df['SlowSMA'], df['SlowSMA'] > df['FastSMA'])
        df = utils.round_df(df)
        return df


class Volume(IndicatorRunner):
    def __init__(self, name='Volume', period=20):
        super().__init__(name, 'volume_{}'.format(period))
        self.period = period

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(index=df_quotes.index)
        ema = self.factory.create(EMA, period=self.period, field='Volume').run(symbol, df_quotes)
        df['Volume'] = df_quotes.Volume
        df['EMA'] = ema.EMA

        self.add_direction(df, np.logical_and(df['Volume'] > df['EMA'], df['Volume'].shift(1) < df['EMA'].shift(1)),
                           np.logical_and(df['Volume'] < df['EMA'], df['Volume'].shift(1) > df['EMA'].shift(1)))
        df = utils.round_df(df)
        return df


class TrendStrength(IndicatorRunner):
    def __init__(self, name='TrendStrength', start=40, end=150, step=5):
        super().__init__(name, 'trend_strength_{}_{}_{}'.format(start, end, step))
        self.start = start
        self.end = end
        self.step = step

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(index=df_quotes.index)
        columns = [x for x in range(self.start, self.end, self.step)]
        columns += [self.end]
        for col in columns:
            df['SMA{}'.format(col)] = self.factory.create(SMA, period=col).run(symbol, df_quotes)['SMA']
        col_size = len(columns)
        df_comparison = df.lt(df_quotes.Close, axis=0)
        df_comparison['CountSMABelowPrice'] = round(100 * (df_comparison.filter(like='SMA') == True).astype(int).sum(axis=1) / col_size)
        df_comparison['CountSMAAbovePrice'] = round(100 * -(df_comparison.filter(like='SMA') == False).astype(int).sum(axis=1) / col_size)
        df['TrendStrength'] = df_comparison.CountSMABelowPrice + df_comparison.CountSMAAbovePrice

        self.add_direction(df, np.logical_and(df.TrendStrength >= 100, df.TrendStrength.shift(1) < 100),
                           np.logical_and(df.TrendStrength <= -100, df_quotes.High < df.filter(like='SMA').min(axis=1)))
        df = utils.round_df(df)
        return df


class BollingerBand(IndicatorRunner):
    def __init__(self, name='BollingerBand', period=50, stdev=2):
        super().__init__(name, 'bollinger_band_{}_{}'.format(period, stdev))
        self.period = period
        self.stdev = stdev

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = pd.DataFrame(index=df_quotes.index)
        df_sma = self.factory.create(SMA, period=self.period).run(symbol, df_quotes)
        df_stdev = self.factory.create(STDEV, period=self.period).run(symbol, df_quotes)
        df['Top'] = df_sma.SMA + (df_stdev.STDEV * self.stdev)
        df['Mid'] = df_sma.SMA
        df['Bottom'] = df_sma.SMA - (df_stdev.STDEV * self.stdev)

        self.add_direction(df, df_quotes.Close >= df.Top, df_quotes.High < df.Bottom)
        df = utils.round_df(df)
        return df


class RSI(IndicatorRunner):
    def __init__(self, name='RSI', period=20, field='Close'):
        super().__init__(name, 'rsi_{}_{}'.format(field, period))
        self.period = period
        self.field = field

    def SMMA(self, series, window=14):
        smma = series.ewm(
            ignore_na=False, alpha=1.0 / window,
            min_periods=0, adjust=True).mean()
        return smma

    def run(self, symbol, df_quotes, df_indicator=None):
        if self.is_updated(df_quotes, df_indicator):
            return df_indicator

        d = df_quotes[self.field].diff()
        df = pd.DataFrame()

        p_ema = self.SMMA((d + d.abs()) / 2, window=self.period)
        n_ema = self.SMMA((-d + d.abs()) / 2, window=self.period)

        df['RS'] = rs = p_ema / n_ema
        df['RSI'] = 100 - 100 / (1.0 + rs)

        self.add_direction(df, False, False)
        return df


class PickleIndicatorRunnerWrapper(object):
    def __init__(self, dir_path, runner):
        self.dir_path = dir_path
        self.runner = runner
        self.unique_name = runner.unique_name
        self.name = runner.name

    def get_save_path(self, symbol, df_quotes):
        return self.dir_path / '{}.{}'.format(symbol, config.PICKLE_EXTENSION)

    def update(self, symbol, df_quotes, df_indicator):
        if self.runner.is_updated(df_quotes, df_indicator):
            return df_indicator

        df = self.runner.run(symbol, df_quotes, df_indicator)
        save_path = self.get_save_path(symbol, df_quotes)
        utils.makedirs(save_path.parent)
        df.to_pickle(save_path)
        return df

    def run(self, symbol, df_quotes, df_indicator=None):
        if os.path.exists(self.get_save_path(symbol, df_quotes)):
            return self.update(symbol, df_quotes, pd.read_pickle(self.get_save_path(symbol, df_quotes)))
        else:
            return self.update(symbol, df_quotes, df_indicator)


class PickleIndicatorRunnerFactory(IndicatorRunnerFactory):
    def __init__(self, dir_path: Path):
        self.dir_path = dir_path

    def create(self, cls, *args, **kwargs):
        runner = cls(*args, **kwargs)
        runner.factory = PickleIndicatorRunnerFactory(self.dir_path)
        save_path = self.dir_path / runner.unique_name
        return PickleIndicatorRunnerWrapper(save_path, runner)


class Attribute(entity.Attribute):
    def __init__(self, df_values):
        self.df_values = df_values

    def get_value(self, date=None, symbol=None):
        df = self.df_values
        if date is not None:
            df = df.loc[date]
        if symbol is not None:
            return df[symbol]
        return df


class Indicator(entity.Indicator):
    def __init__(self, name, attributes):
        super().__init__(name, attributes)

    def get_attribute(self, key):
        if key in self.attributes.keys():
            return self.attributes[key]
        else:
            return None

    def get_attribute_keys(self):
        return self.attributes.keys()


class IndicatorFactory(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def create(self, runner_class, *args, **kwargs):
        raise NotImplementedError


class PickleIndicatorFactory(IndicatorFactory):
    def __init__(self, dir_path: Path, market: Market):
        self.dir_path = dir_path
        self.market = market
        self.runner_factory = PickleIndicatorRunnerFactory(dir_path)

    def create(self, runner_class, *args, **kwargs):
        runner = self.runner_factory.create(runner_class, *args, **kwargs)
        indicator = Indicator(runner.unique_name, dict())
        for symbol in self.market.get_symbols():
            df_quotes = self.market.get_quotes(symbol=symbol)
            df = runner.run(symbol, df_quotes)
            for col in df.columns:
                indicator.attributes[col] = indicator.get_attribute(col) or Attribute(pd.DataFrame())
                indicator.get_attribute(col).df_values[symbol] = df[col]
        return indicator
