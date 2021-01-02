import logging
import pdb
import datetime
import pandas as pd
import os

from oanda.connect import Connect
from config import CONFIG
from utils import *
from candle.candle import *
from candle.candlelist import CandleList
from candle.candlelist_utils import *
from trade_utils import *
from trade import Trade

# create logger
tb_logger = logging.getLogger(__name__)
tb_logger.setLevel(logging.DEBUG)

class TradeBot(object):
    '''
    This class represents an automatic Trading bot

    Class variables
    ---------------
    start: datetime, Required
           Datetime that this Bot will start operating. i.e. 20-03-2017 08:20:00s
    end: datetime, Required
         Datetime that this Bot will end operating. i.e. 20-03-2020 08:20:00s
    pair: str, Required
          Currency pair used in the trade. i.e. AUD_USD
    timeframe: str, Required
               Timeframe used for the trade. Possible values are: D,H12,H10,H8,H4
    '''
    def __init__(self, start, end, pair, timeframe):
        self.start = start
        self.end = end
        self.pair = pair
        self.timeframe = timeframe

    def adjust_SL(self, type, clObj):
        '''
        Function to adjust the SL price
        to the most recent highest high/lowest low

        Parameters
        ----------
        type : str
               Trade type ('long'/ 'short')
        clObj : CandleList obj

        Returns
        -------
        float: adjusted SL
        '''

        if type == 'short':
            part = 'high{0}'.format(CONFIG.get('general', 'bit'))
        elif type == 'long':
            part = 'low{0}'.format(CONFIG.get('general', 'bit'))

        SL = None
        ix = 0
        for c in reversed(clObj.data['candles']):
            # only go back 5 candles
            if ix == 5:
                break
            ix += 1
            price = c[part]
            if SL is None:
                SL = price
                continue
            if type == 'short':
                if price > SL:
                    SL = price
            if type == 'long':
                if price < SL:
                    SL = price

        return SL

    def prepare_trade(self, type, SL, ic, harea_sel, delta,
                      add_pips):
        '''
        Prepare a Trade object
        and check if it is taken

        Parameters
        ----------
        type : str,
               Type of trade. 'short' or 'long'
        SL : float,
             Adjusted (by '__get_trade_type') SL price
        ic : Candle object
             Indecision candle for this trade
        harea_sel : HArea of this trade
        delta : Timedelta object corresponding to
                the time that needs to be increased
        add_pips : Number of pips above/below SL and entry
                   price to consider for recalculating
                   the SL and entry. Default : None

        Returns
        -------
        Trade object
        '''
        startO = ic.time + delta
        if type == 'short':
            # entry price will be the low of IC
            entry_p = getattr(ic, "low{0}".format(CONFIG.get('general', 'bit')))
            if add_pips is not None:
                SL = round(add_pips2price(self.pair,
                                          SL, add_pips), 4)
                entry_p = round(substract_pips2price(self.pair,
                                                     entry_p, add_pips), 4)
        elif type == 'long':
            # entry price will be the high of IC
            entry_p = getattr(ic, "high{0}".format(CONFIG.get('general', 'bit')))
            if add_pips is not None:
                entry_p = add_pips2price(self.pair,
                                    entry_p, add_pips)
                SL = substract_pips2price(self.pair,
                                          SL, add_pips)


        startO = ic.time+delta
        t = Trade(
            id='{0}.bot'.format(self.pair),
            start=startO.strftime('%Y-%m-%d %H:%M:%S'),
            pair=self.pair,
            timeframe=self.timeframe,
            type=type,
            entry=entry_p,
            SR=harea_sel.price,
            SL=SL,
            RR=CONFIG.getfloat('trade_bot', 'RR'),
            strat='counter')

        return t

    def run(self, discard_sat=True):
        '''
        This function will run the Bot from start to end
        one candle at a time

        Parameter
        ---------
        discard_sat : Bool
                      If this is set to True, then the Trade wil not
                      be taken if IC falls on a Saturday. Default: True

        Returns
        -------
        TradeList object with Trades taken. None if no trades
        were taken
        '''
        tb_logger.info("Running...")

        conn = Connect(instrument=self.pair,
                       granularity=self.timeframe)

        ser_file = None
        if CONFIG.has_option('general', 'ser_data_file'):
            ser_file = CONFIG.get('general', 'ser_data_file')

        delta = nhours = None
        if self.timeframe == "D":
            nhours = 24
            delta = timedelta(hours=24)
        else:
            p1 = re.compile('^H')
            m1 = p1.match(self.timeframe)
            if m1:
                nhours = int(self.timeframe.replace('H', ''))
                delta = timedelta(hours=int(nhours))

        # convert to datetime the start and end for this TradeBot
        startO = pd.datetime.strptime(self.start, '%Y-%m-%d %H:%M:%S')
        endO = pd.datetime.strptime(self.end, '%Y-%m-%d %H:%M:%S')

        loop = 0
        tlist = []
        tend = SRlst = None
        # calculate the start datetime for the CList that will be used
        # for calculating the S/R areas
        delta_period = periodToDelta(CONFIG.getint('trade_bot', 'period_range'),
                                     self.timeframe)
        initc_date = startO-delta_period
        # Get now a CandleList from 'initc_date' to 'startO' which is the
        # total time interval for this TradeBot
        res = conn.query(start=initc_date.isoformat(),
                         end=endO.isoformat(),
                         infile=ser_file)

        clO = CandleList(res)
        while startO <= endO:
            if tend is not None:
                # this means that there is currently an active trade
                if startO <= tend:
                    startO = startO + delta
                    loop += 1
                    continue
                else:
                    tend = None
            tb_logger.info("Trade bot - analyzing candle: {0}".format(startO.isoformat()))
            sub_clO = clO.slice(initc_date,
                                startO)
            dt_str = startO.strftime("%d_%m_%Y_%H_%M")
            if loop == 0:
                outfile_txt = "{0}/srareas/{1}.{2}.{3}.halist.txt".format(CONFIG.get("images", "outdir"),
                                                                        self.pair, self.timeframe, dt_str)
                outfile_png = "{0}/srareas/{1}.{2}.{3}.halist.png".format(CONFIG.get("images", "outdir"),
                                                                          self.pair, self.timeframe, dt_str)
                SRlst = calc_SR(sub_clO, outfile=outfile_png)
                f = open(outfile_txt, 'w')
                res = SRlst.print()
                # print SR report to file
                f.write(res)
                f.close()
                tb_logger.info("Identified HAreaList for time {0}:".format(startO.isoformat()))
                tb_logger.info("{0}".format(res))
            elif loop >= CONFIG.getint('trade_bot',
                                       'period'):
                # An entire cycle has occurred. Invoke .calc_SR
                outfile_txt = "{0}/srareas/{1}.{2}.{3}.halist.txt".format(CONFIG.get("images", "outdir"),
                                                                      self.pair, self.timeframe, dt_str)
                outfile_png = "{0}/srareas/{1}.{2}.{3}.halist.png".format(CONFIG.get("images", "outdir"),
                                                                          self.pair, self.timeframe, dt_str)
                SRlst = calc_SR(sub_clO, outfile=outfile_png)
                f = open(outfile_txt, 'w')
                res = SRlst.print()
                tb_logger.info("Identified HAreaList for time {0}:".format(startO.isoformat()))
                tb_logger.info("{0}".format(res))
                # print SR report to file
                f.write(res)
                f.close()
                loop = 0

            # fetch candle for current datetime
            res = conn.query(start=startO.isoformat(),
                             count=1,
                             infile=ser_file)

            # this is the current candle that
            # is being checked
            c_candle = Candle(dict_data=res['candles'][0])
            c_candle.time = datetime.strptime(c_candle.time,
                                              '%Y-%m-%dT%H:%M:%S.%fZ')

            # c_candle.time is not equal to startO
            # when startO is non-working day, for example
            delta1hr = timedelta(hours=1)
            if (c_candle.time != startO) and (abs(c_candle.time-startO) > delta1hr):
                loop += 1
                tb_logger.info("Analysed dt {0} is not the same than APIs returned dt {1}."
                               " Skipping...".format(startO, c_candle.time))
                startO = startO + delta
                continue

            #check if there is any HArea overlapping with c_candle
            HAreaSel, sel_ix = SRlst.onArea(candle=c_candle)

            if HAreaSel is not None:
                c_candle.set_candle_features()
                # guess the if trade is 'long' or 'short'
                newCl = clO.slice(start=initc_date, end=c_candle.time)
                type = get_trade_type(c_candle.time, newCl)
                SL = self.adjust_SL(type, newCl )
                prepare_trade = False
                if c_candle.indecision_c(ic_perc=CONFIG.getint('general', 'ic_perc')) is True:
                    prepare_trade = True
                elif type == 'short' and c_candle.colour == 'red':
                    prepare_trade = True
                elif type == 'long' and c_candle.colour == 'green':
                    prepare_trade = True

                # discard if IC falls on a Saturday
                if c_candle.time.weekday() == 5 and discard_sat is True:
                    tb_logger.info("Possible trade at {0} falls on Sat. Skipping...".format(c_candle.time))
                    prepare_trade = False

                if prepare_trade is True:
                    t = self.prepare_trade(
                        type=type,
                        SL=SL,
                        ic=c_candle,
                        harea_sel=HAreaSel,
                        delta=delta,
                        add_pips=CONFIG.getint('trade', 'add_pips'))
                    t.tot_SR = len(SRlst.halist)
                    t.rank_selSR = sel_ix
                    t.SRlst = SRlst
                    # calculate t.entry-t.SL in number of pips
                    # and discard if it is over threshold
                    diff = abs(t.entry-t.SL)
                    number_pips = float(calculate_pips(self.pair, diff))
                    if number_pips > CONFIG.getint('trade_bot', 'SL_width_pips'):
                        loop += 1
                        startO = startO + delta
                        continue
                    else:
                        tlist.append(t)
            startO = startO+delta
            loop += 1

        tb_logger.info("Run done")

        if len(tlist) == 0:
            return None
        else:
            return tlist