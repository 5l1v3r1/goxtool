#!/usr/bin/env python2

"""
Tool to display live MtGox market info and
framework for experimenting with trading bots
"""
#  Copyright (c) 2013 Bernd Kreuss <prof7bit@gmail.com>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

# pylint: disable=C0301

import argparse
import curses
import goxapi
import logging
import math
import sys
import traceback


#
#
# curses user interface
#

HEIGHT_STATUS   = 2
HEIGHT_CON      = 7
WIDTH_ORDERBOOK = 45

COLORS =    [["con_text",       curses.COLOR_BLUE,    curses.COLOR_CYAN]
            ,["status_text",    curses.COLOR_BLUE,    curses.COLOR_CYAN]

            ,["book_text",      curses.COLOR_BLACK,   curses.COLOR_BLUE]
            ,["book_bid",       curses.COLOR_BLACK,   curses.COLOR_GREEN]
            ,["book_ask",       curses.COLOR_BLACK,   curses.COLOR_RED]
            ,["book_own",       curses.COLOR_BLACK,   curses.COLOR_YELLOW]
            ,["book_vol",       curses.COLOR_BLACK,   curses.COLOR_BLUE]

            ,["chart_text",     curses.COLOR_BLACK,   curses.COLOR_WHITE]
            ,["chart_up",       curses.COLOR_BLACK,   curses.COLOR_GREEN]
            ,["chart_down",     curses.COLOR_BLACK,   curses.COLOR_RED]
            ,["order_pending",  curses.COLOR_BLACK,   curses.COLOR_BLUE]
            ]

COLOR_PAIR = {}

def init_colors():
    """initialize curses color pairs and give them names. The color pair
    can then later quickly be retrieved from the COLOR_PAIR[] dict"""
    index = 1
    for (name, back, fore) in COLORS:
        curses.init_pair(index, fore, back)
        COLOR_PAIR[name] = curses.color_pair(index)
        index += 1

class Win:
    """represents a curses window"""
    # pylint: disable=R0902

    def __init__(self, stdscr):
        """create and initialize the window. This will also subsequently
        call the paint() method."""
        self.stdscr = stdscr
        self.posx = 0
        self.posy = 0
        self.width = 10
        self.height = 10
        self.termwidth = 10
        self.termheight = 10
        self.win = None
        self.__create_win()

    def calc_size(self):
        """override this method to change posx, posy, width, height.
        It will be called before window creation and on resize."""
        pass

    def paint(self):
        """paint the window. Override this with your own implementation.
        This method must paint the entire window contents from scratch.
        It is automatically called after the window has been initially
        created and also after every resize. Call it explicitly when
        your data has changed and must be displayed"""
        self.win.touchwin()
        self.win.refresh()

    def resize(self):
        """You must call this method from your main loop when the
        terminal has been resized. It will subsequently make it
        recalculate its own new size and then call its paint() method"""
        del self.win
        self.__create_win()

    def __create_win(self):
        """create the window. This will also be called on every resize,
        windows won't be moved, they will be deleted and recreated."""
        self.__calc_size()
        self.win = curses.newwin(self.height, self.width, self.posy, self.posx)
        self.win.scrollok(True)
        self.paint()

    def __calc_size(self):
        """calculate the default values for positionand size. By default
        this will result in a window covering the entire terminal.
        Implement the calc_size() method (which will be called afterwards)
        to change (some of) these values according to your needs."""
        maxyx = self.stdscr.getmaxyx()
        self.termwidth = maxyx[1]
        self.termheight = maxyx[0]
        self.posx = 0
        self.posy = 0
        self.width = self.termwidth
        self.height = self.termheight
        self.calc_size()


class WinConsole(Win):
    """The console window at the bottom"""
    def __init__(self, stdscr, gox):
        """create the console window and connect it to the Gox debug
        callback function"""
        self.gox = gox
        gox.signal_debug.connect(self.slot_debug)
        Win.__init__(self, stdscr)

    def paint(self):
        """just empty the window after resize (I am lazy)"""
        self.win.bkgd(" ", COLOR_PAIR["con_text"])
        self.win.refresh()

    def resize(self):
        """resize and print a log message. Old messages will have been
        lost after resize because of my dumb paint() implementation, so
        at least print a message indicating that fact into the
        otherwise now empty console window"""
        Win.resize(self)
        self.write("### console has been resized")

    def calc_size(self):
        """put it at the bottom of the screen"""
        self.height = HEIGHT_CON
        self.posy = self.termheight - self.height

    def slot_debug(self, dummy_gox, (txt)):
        """this slot will be connected to all debug signals."""
        self.write(txt)

    def write(self, txt):
        """write a line of text, scroll if needed"""
        self.win.addstr("\n" + txt,  COLOR_PAIR["con_text"])
        self.win.refresh()


class WinOrderBook(Win):
    """the orderbook window"""

    def __init__(self, stdscr, gox):
        """create the orderbook window and connect it to the
        onChanged callback of the gox.orderbook instance"""
        self.gox = gox
        gox.orderbook.signal_changed.connect(self.slot_changed)
        Win.__init__(self, stdscr)

    def calc_size(self):
        """put it into the middle left side"""
        self.height = self.termheight - HEIGHT_CON - HEIGHT_STATUS
        self.posy = HEIGHT_STATUS
        self.width = WIDTH_ORDERBOOK

    def paint(self):
        """paint the visible portion of the orderbook"""
        self.win.bkgd(" ",  COLOR_PAIR["book_text"])
        self.win.erase()
        mid = self.height / 2
        col_bid = COLOR_PAIR["book_bid"]
        col_ask = COLOR_PAIR["book_ask"]
        col_vol = COLOR_PAIR["book_vol"]
        col_own = COLOR_PAIR["book_own"]

        # print the asks
        # pylint: disable=C0301
        book = self.gox.orderbook
        pos = mid - 1
        i = 0
        cnt = len(book.asks)
        while pos >= 0 and  i < cnt:
            self.win.addstr(pos, 0,  goxapi.int2str(book.asks[i].price, book.gox.currency), col_ask)
            self.win.addstr(pos, 12, goxapi.int2str(book.asks[i].volume, "BTC"), col_vol)
            ownvol = book.get_own_volume_at(book.asks[i].price)
            if ownvol:
                self.win.addstr(pos, 28, goxapi.int2str(ownvol, "BTC"), col_own)
            pos -= 1
            i += 1

        # print the bids
        pos = mid + 1
        i = 0
        cnt = len(book.bids)
        while pos < self.height and  i < cnt:
            self.win.addstr(pos, 0,  goxapi.int2str(book.bids[i].price, book.gox.currency), col_bid)
            self.win.addstr(pos, 12, goxapi.int2str(book.bids[i].volume, "BTC"), col_vol)
            ownvol = book.get_own_volume_at(book.bids[i].price)
            if ownvol:
                self.win.addstr(pos, 28, goxapi.int2str(ownvol, "BTC"), col_own)
            pos += 1
            i += 1

        self.win.refresh()


    def slot_changed(self, book, dummy_data):
        """Slot for orderbook.signal_changed"""
        self.paint()

        if self.gox.config.get_bool("goxtool", "set_xterm_title"):
            last_candle = self.gox.history.last_candle()
            if last_candle:
                title = goxapi.int2str(last_candle.cls, self.gox.currency).strip()
                title += " - goxtool -"
                title += " bid:" + goxapi.int2str(book.bid, self.gox.currency).strip()
                title += " ask:" + goxapi.int2str(book.ask, self.gox.currency).strip()
                curses.putp("\033]0;%s\007" % title)


class WinChart(Win):
    """the chart window"""

    def __init__(self, stdscr, gox):
        self.gox = gox
        self.pmin = 0
        self.pmax = 0
        gox.history.signal_changed.connect(self.slot_hist_changed)
        gox.orderbook.signal_changed.connect(self.slot_book_changed)
        Win.__init__(self, stdscr)

    def calc_size(self):
        """position in the middle, right to the orderbook"""
        self.posx = WIDTH_ORDERBOOK
        self.posy = HEIGHT_STATUS
        self.width = self.termwidth - WIDTH_ORDERBOOK
        self.height = self.termheight - HEIGHT_CON - HEIGHT_STATUS

    def is_in_range(self, price):
        """is this price in the currently viible range?"""
        return price <= self.pmax and price >= self.pmin

    def get_optimal_step(self, num_min):
        """return optimal step size for painting y-axis labels so that the
        range will be divided into at least num_min steps"""
        if self.pmax <= self.pmin:
            return None
        stepex = float(self.pmax - self.pmin) / num_min
        step1 = math.pow(10, math.floor(math.log(stepex, 10)))
        step2 = step1 * 2
        step5 = step1 * 5
        if step5 <= stepex:
            return step5
        if step2 <= stepex:
            return step2
        return step1

    def price_to_screen(self, price):
        """convert price into screen coordinates (y=0 is at the top!)"""
        relative_from_bottom = \
            float(price - self.pmin) / float(self.pmax - self.pmin)
        screen_from_bottom = relative_from_bottom * self.height
        return int(self.height - screen_from_bottom)

    def addch_safe(self, posy, posx, character, color_pair):
        """place a character but don't throw error in lower right corner"""
        if posy < 0 or posy > self.height - 1:
            return
        if posx < 0 or posx > self.width - 1:
            return
        if posx == self.width - 1 and posy == self.height - 1:
            return
        self.win.addch(posy, posx, character, color_pair)

    def paint_candle(self, posx, candle):
        """paint a single candle"""

        sopen  = self.price_to_screen(candle.opn)
        shigh  = self.price_to_screen(candle.hig)
        slow   = self.price_to_screen(candle.low)
        sclose = self.price_to_screen(candle.cls)

        for posy in range(self.height):
            if posy >= shigh and posy < sopen and posy < sclose:
                # upper wick
                # pylint: disable=E1101
                self.addch_safe(posy, posx,
                    curses.ACS_VLINE, COLOR_PAIR["chart_text"])
            if posy >= sopen and posy < sclose:
                # red body
                self.addch_safe(posy, posx,
                    ord(" "), curses.A_REVERSE + COLOR_PAIR["chart_down"])
            if posy >= sclose and posy < sopen:
                # green body
                self.addch_safe(posy, posx,
                    ord(" "), curses.A_REVERSE + COLOR_PAIR["chart_up"])
            if posy >= sopen and posy >= sclose and posy < slow:
                # lower wick
                # pylint: disable=E1101
                self.addch_safe(posy, posx,
                    curses.ACS_VLINE, COLOR_PAIR["chart_text"])

    def paint(self):
        """paint the visible portion of the chart"""


        self.win.bkgd(" ",  COLOR_PAIR["chart_text"])
        self.win.erase()

        hist = self.gox.history
        book = self.gox.orderbook

        self.pmax = 0
        self.pmin = 9999999999

        # determine y range
        posx = self.width - 2
        index = 0
        while index < hist.length() and posx >= 0:
            candle = hist.candles[index]
            if self.pmax < candle.hig:
                self.pmax = candle.hig
            if self.pmin > candle.low:
                self.pmin = candle.low
            index += 1
            posx -= 1

        if self.pmax == self.pmin:
            return

        # paint the candles
        posx = self.width - 2
        index = 0
        while index < hist.length() and posx >= 0:
            candle = hist.candles[index]
            self.paint_candle(posx, candle)
            index += 1
            posx -= 1

        # paint bid, ask, own orders
        posx = self.width - 1
        for order in book.owns:
            if self.is_in_range(order.price):
                posy = self.price_to_screen(order.price)
                if order.status == "pending":
                    self.addch_safe(posy, posx,
                        ord("o"), COLOR_PAIR["order_pending"])
                else:
                    self.addch_safe(posy, posx,
                        ord("O"), COLOR_PAIR["chart_text"])

        if self.is_in_range(book.bid):
            posy = self.price_to_screen(book.bid)
            # pylint: disable=E1101
            self.addch_safe(posy, posx,
                curses.ACS_HLINE, COLOR_PAIR["chart_up"])

        if self.is_in_range(book.ask):
            posy = self.price_to_screen(book.ask)
            # pylint: disable=E1101
            self.addch_safe(posy, posx,
                curses.ACS_HLINE, COLOR_PAIR["chart_down"])

        # paint the y-axis labels
        posx = 0
        step = self.get_optimal_step(4)
        if step:
            labelprice = int(self.pmin / step) * step
            while not labelprice > self.pmax:
                posy = self.price_to_screen(labelprice)
                if posy < self.height - 1:
                    self.win.addstr(
                        posy, posx,
                        goxapi.int2str(labelprice, self.gox.currency),
                        COLOR_PAIR["chart_text"]
                    )
                labelprice += step

        self.win.refresh()

    def slot_hist_changed(self, dummy_history, (dummy_cnt)):
        """Slot for history.signal_changed"""
        self.paint()

    def slot_book_changed(self, dummy_book, dummy_data):
        """Slot for orderbook.signal_changed"""
        self.paint()


class WinStatus(Win):
    """the status window at the top"""

    def __init__(self, stdscr, gox):
        """create the status window and connect the needed callbacks"""
        self.gox = gox
        gox.signal_wallet.connect(self.slot_status_changed)
        Win.__init__(self, stdscr)

    def calc_size(self):
        """place it at the top of the terminal"""
        self.height = HEIGHT_STATUS

    def paint(self):
        """paint the complete status"""
        self.win.bkgd(" ", COLOR_PAIR["status_text"])
        self.win.erase()
        line1 = "Currency: " + self.gox.currency + " | "
        line1 += "Account: "
        if len(self.gox.wallet):
            for currency in self.gox.wallet:
                line1 += currency + " " \
                + goxapi.int2str(self.gox.wallet[currency], currency).strip() \
                + " + "
            line1 = line1.strip(" +")
        else:
            line1 += "No info (yet)"
        self.win.addstr(0, 0, line1, COLOR_PAIR["status_text"])
        self.win.refresh()

    def slot_status_changed(self, dummy_sender, dummy_data):
        """the callback funtion called by the Gox() instance"""
        self.paint()


#
#
# logging
#

def slot_debug(sender, (msg)):
    """handler for signal_debug signals"""
    logging.debug("%s:%s", sender.__class__.__name__, msg)

def logging_init(gox):
    """initialize logger and connect to signal_debug signals"""
    logging.basicConfig(filename='goxtool1.log'
                       ,filemode='w'
                       ,format='%(asctime)s:%(levelname)s:%(message)s'
                       ,level=logging.DEBUG
                       )
    gox.signal_debug.connect(slot_debug)

#
#
# dynamically (re)loadable strategy module
#

class StrategyManager():
    """load the strategy module"""

    def __init__(self, gox, strategy_module_name):
        self.strategy_object = None
        self.strategy_module_name = strategy_module_name
        self.gox = gox
        self.reload()

    def reload(self):
        """reload and re-initialize the strategy module"""
        try:
            strategy_module = __import__(self.strategy_module_name)
            try:
                if self.strategy_object:
                    self.strategy_object.on_before_unload(self.gox)
                reload(strategy_module)
                self.strategy_object = strategy_module.Strategy(self.gox)

            # pylint: disable=W0703
            except Exception:
                self.gox.debug(traceback.format_exc())

        except ImportError:
            self.gox.debug("### could not import %s.py"
                % self.strategy_module_name)
            self.gox.debug("### running without strategy module")


    def call_key(self, key):
        """try to call the on_key_* method in the strategymodule if it exists"""
        try:
            method = getattr(self.strategy_object, "on_key_%s" % key)
            try:
                method(self.gox)

            # pylint: disable=W0703
            except Exception:
                self.gox.debug(traceback.format_exc())

        except AttributeError:
            self.gox.debug("### no handler defined for key: '%s'" % key)


#
#
# main program
#

def main():
    """main funtion, called from within the curses.wrapper"""

    def curses_loop(stdscr):
        """This code runs within curses environment"""
        init_colors()

        gox = goxapi.Gox(secret, config)

        conwin = WinConsole(stdscr, gox)
        bookwin = WinOrderBook(stdscr, gox)
        statuswin = WinStatus(stdscr, gox)
        chartwin = WinChart(stdscr, gox)

        logging_init(gox)
        strategy_manager = StrategyManager(gox, strat_mod_name)

        gox.start()
        while True:
            key = conwin.win.getch()
            if key == ord("q"):
                break
            if key == curses.KEY_RESIZE:
                stdscr.erase()
                stdscr.refresh()
                conwin.resize()
                bookwin.resize()
                chartwin.resize()
                statuswin.resize()
                continue
            if key == ord("l"):
                strategy_manager.reload()
                continue
            if key > ord("a") and key < ord("z"):
                strategy_manager.call_key(chr(key))

        # shutdown; no more ugly tracebacks from here on
        sys.excepthook = lambda x, y, z: None


    # before we can finally start the curses UI we might need to do some user
    # interaction on the command line, regarding the encrypted secret
    argp = argparse.ArgumentParser(description='MtGox live market data monitor'
        + ' and trading bot experimentation framework')
    argp.add_argument('--add-secret', action="store_true",
        help="prompt for API secret, encrypt it and then exit")
    argp.add_argument('--strategy', action="store", default="strategy.py",
        help="name of strategy module file, default=strategy.py")
    args = argp.parse_args()

    config = goxapi.GoxConfig("goxtool.ini")
    secret = goxapi.Secret(config)
    if args.add_secret:
        # prompt for secret, encrypt and exit
        secret.prompt_encrypt()
    else:
        strat_mod_name = args.strategy.replace(".py", "")
        if secret.prompt_decrypt() != secret.S_FAIL_FATAL:
            curses.wrapper(curses_loop)
            print
            print "*******************************************************"
            print "*  Please donate: 1D7ELjGofBiRUJNwK55DVC3XWYjfN77CA3  *"
            print "*******************************************************"


if __name__ == "__main__":
    main()

