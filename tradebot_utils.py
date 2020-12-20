from oanda.connect import Connect
from utils import *
from config import CONFIG
from candle.candlelist import CandleList
from trade import Trade
from harea import HArea, HAreaList
import pandas as pd

import logging

# create logger
tb_logger = logging.getLogger(__name__)
tb_logger.setLevel(logging.DEBUG)

def get_max_min(tbO, adateObj):
    '''
    Function to get the price range for identifying S/R by checking the max
    and min price for CandleList starting in 'adateObj'- CONFIG.getint('trade_bot', 'period_range')
    and ending in 'adateObj'

    Parameters
    ----------
    tbO: TradeBot object
         Used for calculation
    adateObj: datetime object used for identifying
              S/R areas

    Returns
    -------
    max, min floats
    '''
    conn = Connect(instrument=tbO.pair,
                   granularity=tbO.timeframe)

    delta_period = periodToDelta(CONFIG.getint('trade_bot', 'period_range'),
                                 tbO.timeframe)
    delta_1 = periodToDelta(1, tbO.timeframe)

    start = adateObj - delta_period  # get the start datetime for this CandleList period
    end = adateObj + delta_1  # increase self.start by one candle to include self.start

    tb_logger.info("Fetching data from API")
    res = conn.query(start=start.isoformat(),
                     end=end.isoformat())

    cl = CandleList(res)

    max = cl.get_highest()
    min = cl.get_lowest()

    # add a number of pips to max,min to be sure that we
    # also detect the extreme pivots
    max = add_pips2price(tbO.pair, max, CONFIG.getint('trade_bot', 'add_pips'))
    min = substract_pips2price(tbO.pair, min, CONFIG.getint('trade_bot', 'add_pips'))

    return round(max,4), round(min,4)

def calc_SR(tbO, start, end):
    '''
    Function to calculate S/R lines

    Parameters
    ----------
    tbO: TradeBot object
         Used for calculation
    start: start datetime object used for the CandleList to identify
           S/R areas
    end: end datetime object used for the CandleList to identify
         S/R areas

    Return
    ------
    HAreaList object
    '''

    # calculate price range for calculating S/R
    ul, ll = get_max_min(tbO, end)
    tb_logger.info("Running calc_SR for estimated range: {0}-{1}".format(ll, ul))

    prices, bounces, score_per_bounce, tot_score = ([] for i in range(4))

    # the increment of price in number of pips is double the hr_extension
    prev_p = None
    p = float(ll)

    conn = Connect(instrument=tbO.pair,
                   granularity=tbO.timeframe)

    res = conn.query(start=start.isoformat(),
                     end=end.isoformat())
    clO = CandleList(res)
    PL = clO.get_pivotlist(th_bounces=CONFIG.getfloat('pivots', 'th_bounces'))

    while p <= float(ul):
        tb_logger.debug("Processing S/R at {0}".format(round(p, 4)))
        # each of 'p' will become a S/R that will be tested for bounces
        # set entry to price+self.settings.getint('trade_bot','i_pips')
        entry = add_pips2price(tbO.pair, p, CONFIG.getint('trade_bot', 'i_pips'))
        # set S/L to price-self.settings.getint('trade_bot','i_pips')
        SL = substract_pips2price(tbO.pair, p, CONFIG.getint('trade_bot', 'i_pips'))

        # get a PivotList for this particular S/R
        newPL = PL.inarea_pivots(SR=p)
        if len(newPL.plist) == 0:
            mean_pivot = 0
        else:
            mean_pivot = newPL.get_avg_score()

        prices.append(round(p, 5))
        bounces.append(len(newPL.plist))
        tot_score.append(newPL.get_score())
        score_per_bounce.append(mean_pivot)
        # increment price to following price.
        # Because the increment is made in pips
        # it does not suffer of the JPY pairs
        # issue
        p = add_pips2price(tbO.pair, p, 2*CONFIG.getint('trade_bot', 'i_pips'))
        if prev_p is None:
            prev_p = p
        else:
            increment_price = round(p - prev_p, 5)
            prev_p = p

    data = {'price': prices,
            'bounces': bounces,
            'scores': score_per_bounce,
            'tot_score': tot_score}

    df = pd.DataFrame(data=data)

    ### establishing bounces threshold as the args.th quantile
    # selecting only rows with at least one pivot and tot_score>0,
    # so threshold selection considers only these rows
    # and selection is not biased when range of prices is wide
    dfgt1 = df.loc[(df['bounces'] > 0)]
    dfgt2 = df.loc[(df['tot_score'] > 0)]
    bounce_th = dfgt1.bounces.quantile(CONFIG.getfloat('trade_bot', 'th'))
    score_th = dfgt2.tot_score.quantile(CONFIG.getfloat('trade_bot', 'th'))

    print("Selected number of pivot threshold: {0}".format(bounce_th))
    print("Selected tot score threshold: {0}".format(round(score_th,1)))

    # selecting records over threshold
    dfsel = df.loc[(df['bounces'] > bounce_th) | (df['tot_score'] > score_th)]

    # repeat until no overlap between prices
    ret = calc_diff(dfsel, increment_price)
    dfsel = ret[0]
    tog_seen = ret[1]
    while tog_seen is True:
        ret = calc_diff(dfsel, increment_price)
        dfsel = ret[0]
        tog_seen = ret[1]

    # iterate over DF with selected SR to create a HAreaList
    halist = []
    for index, row in dfsel.iterrows():
        resist = HArea(price=row['price'],
                       pips=CONFIG.getint('pivots', 'hr_pips'),
                       instrument=tbO.pair,
                       granularity=tbO.timeframe,
                       no_pivots=row['bounces'],
                       tot_score=round(row['tot_score'], 5))
        halist.append(resist)

    halist = HAreaList(halist=halist)

    # Plot the HAreaList
    halist.plot(clO= clO, outfile=CONFIG.get("images", "outdir") +
                                  "/srareas/{0}.{1}.halist.png".format(tbO.pair,
                                                                      tbO.timeframe))

    tb_logger.info("Run done")

    return halist

def calc_diff(df_loc, increment_price):
    '''
    Function to select the best S/R for areas that
    are less than 3*increment_price

    Parameters
    ----------
    df_loc : Pandas dataframe with S/R areas
    increment_price : float
                      This is the increment_price
                      between different price levels
                      in order to identify S/Rs

    Returns
    -------
    Pandas dataframe with selected S/R
    '''
    prev_price = prev_row = prev_ix = None
    tog_seen = False
    for index, row in df_loc.iterrows():
        if prev_price is None:
            prev_price = float(row['price'])
            prev_row = row
            prev_ix = index
        else:
            diff = round(float(row['price']) - prev_price, 4)
            if diff < 3 * increment_price:
                tog_seen = True
                if row['bounces'] <= prev_row['bounces'] and row['tot_score'] < prev_row['tot_score']:
                    # remove current row
                    df_loc.drop(index, inplace=True)
                elif row['bounces'] >= prev_row['bounces'] and row['tot_score'] > prev_row['tot_score']:
                    # remove previous row
                    df_loc.drop(prev_ix, inplace=True)
                    prev_price = float(row['price'])
                    prev_row = row
                    prev_ix = index
                elif row['bounces'] <= prev_row['bounces'] and row['tot_score'] > prev_row['tot_score']:
                    # remove previous row as scores in current takes precedence
                    df_loc.drop(prev_ix, inplace=True)
                    prev_price = float(row['price'])
                    prev_row = row
                    prev_ix = index
                elif row['bounces'] >= prev_row['bounces'] and row['tot_score'] < prev_row['tot_score']:
                    # remove current row as scores in current takes precedence
                    df_loc.drop(index, inplace=True)
                elif row['bounces'] == prev_row['bounces'] and row['tot_score'] == prev_row['tot_score']:
                    # exactly same quality for row and prev_row
                    # remove current arbitrarily
                    df_loc.drop(index, inplace=True)
            else:
                prev_price = float(row['price'])
                prev_row = row
                prev_ix = index
    return df_loc, tog_seen
