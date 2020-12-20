import pytest
import glob
import os
import pdb

from trade_bot import TradeBot

@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    """
    Defining the environment
    """
    monkeypatch.setenv('DATADIR', '../data/')

@pytest.fixture
def clean_tmp():
    yield
    print("Cleanup files")
    files1 = glob.glob(os.getenv('DATADIR')+"imgs/pivots/*")
    files2 = glob.glob(os.getenv('DATADIR')+"imgs/srareas/*")
    files = files1 + files2
    for f in files:
        os.remove(f)

@pytest.fixture
def tb_object():
    tb = TradeBot(
            pair='EUR_GBP',
            timeframe='D',
            start='2019-08-12 22:00:00',
            end='2019-08-19 22:00:00')
    return tb
