from __future__ import print_function
__author__ = 'riteshg'

import sys
import json
import urllib,time,datetime
import MySQLdb as mdb
from time import sleep
from threading import Thread
import pyRserve
import subprocess
import requests

# Run Command in EC2:
# nohup python vwapDataUpdater.py &

# Overall Global Vars
openQuote = "OPEN_QUOTE"
periodicQuote = "PERIODIC_QUOTE"
currTimeQuoteDBUpdateMap = {}
currTimeRExecMap = {}
openingPriceUpdatedStocksList = []
periodicPriceUpdateDict = {}
# DBserverIP = 'localhost'    # DEBUGGING
DBserverIP = '172.31.32.173'
# HTTPServerIp = '52.24.168.159'   # DEBUGGING
HTTPServerIp = 'localhost'

# VWAP Strategy time interval specific global Vars
periodicTimeListFifteenMin = ["09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15",
                            "11:30", "11:45", "12:00", "12:15", "12:30", "12:45", "13:00", "13:15",
                            "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15"]
periodicTimeListFiveMin = ["09:20", "09:25", "09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "10:00",
    "10:05", "10:10", "10:15", "10:20", "10:25", "10:30", "10:35", "10:40", "10:45", "10:50", "10:55", "11:00",
    "11:05", "11:10", "11:15", "11:20", "11:25", "11:30", "11:35", "11:40", "11:45", "11:50", "11:55", "12:00",
    "12:05", "12:10", "12:15", "12:20", "12:25", "12:30", "12:35", "12:40", "12:45", "12:50", "12:55", "13:00",
    "13:05", "13:10", "13:15", "13:20", "13:25", "13:30", "13:35", "13:40", "13:45", "13:50", "13:55", "14:00",
    "14:05", "14:10", "14:15", "14:20", "14:25", "14:30", "14:35", "14:40", "14:45", "14:50", "14:55", "15:00",
    "15:05", "15:10", "15:15"]
vwap_tb_name = 'VWAPFiveMinTable'
vwap_strategy_time_tb_name = 'IntradayFiveMinTable'
time_interval = 300
periodicTimeList = periodicTimeListFiveMin
prevNumOfTradingDays = '5'

# R Specific Global Vars
RServeIP = 'localhost'
Rconn = None
RconnStatus = False
#RFILE_VWAP_FIVEMIN_RECO = r'D:\RiteshComputer\Trading\quant_MyRStrats\vwap\ec2VWAPFiveMinReco.R'    # DEBUGGING
#RSCRIPT_VWAP_FIVEMIN_TRADE_SIGNAL = 'source("D:\\RiteshComputer\\Trading\\quant_MyRStrats\\vwap\\ec2VWAPFiveMinReco.R")'   # DEBUGGING
RFILE_VWAP_FIVEMIN_RECO = r'/home/ubuntu/tradeStrats/vwap/Rcode/ec2VWAPFiveMinReco.R'
RSCRIPT_VWAP_FIVEMIN_TRADE_SIGNAL = 'source("/home/ubuntu/tradeStrats/vwap/Rcode/ec2VWAPFiveMinReco.R")'

'''
Quote Class
'''
class IntradayQuote(object):
    # Date and Time Formats
    DATE_FMT = '%Y-%m-%d'
    TIME_FMT = '%H:%M:%S'

    def __init__(self):
        # initializer
        self.symbol = ''
        self.date, self.time, self.open_, self.high, self.low, self.close, self.volume = ([] for _ in range(7))

    def append(self, dt, open_, high, low, close, volume):
        # Update the fields of the Quote object
        self.date.append(dt.date())     # Date
        self.time.append(dt.time())     # Time
        self.open_.append(float(open_))     # O
        self.high.append(float(high))       # H
        self.low.append(float(low))         # L
        self.close.append(float(close))     # C
        self.volume.append(int(volume))     # Vol

    def to_csv(self):
        # prepare the comma separated line of the quote
        return ''.join(["{0}, {1}, {2}, {3:.2f}, {4:.2f}, {5:.2f}, {6:.2f}, {7}\n".format(self.symbol,
              self.date[bar].strftime('%Y-%m-%d'), self.time[bar].strftime('%H:%M:%S'),
              self.open_[bar], self.high[bar], self.low[bar], self.close[bar], self.volume[bar])
              for bar in xrange(len(self.close))])

    def __repr__(self):
        # repr of the object
        return self.to_csv()

'''
Class to collect the intraday quote
from google finance XHR URL
'''
class GoogleIntradayQuote(IntradayQuote):
    '''
    Method to prepare StockQuote from self
    '''
    def prepareStockQuoteFromSelfData(self, tick):
        stockQuote = {}
        stockQuote['symbol'] = self.symbol
        stockQuote['date'] = self.date[tick]
        stockQuote['time'] = self.time[tick]
        stockQuote['open_'] = self.open_[tick]
        stockQuote['high'] = self.high[tick]
        stockQuote['low'] = self.low[tick]
        stockQuote['close'] = self.close[tick]
        stockQuote['volume'] = self.volume[tick]
        return stockQuote

    '''
    DB update routine of quotes
    '''
    def updateDB(self, stockQuote, currTime):
        # Connect to the MySQL instance
        db_host = DBserverIP
        db_user = 'root'
        db_pass = ''
        db_name = 'StocksDB'   # Remove '_' for execution, accidently DB write proof :)
        tb_name = vwap_tb_name

        # Connect to DB
        # IMPORTANT: DO NOT HANDLE EXCEPTION HERE, R SCRIPT EXEC IS DEPENDENT ON EXCEPTION CHECK
        conn = mdb.connect(host=db_host, user=db_user, passwd=db_pass, db=db_name)
        # prepare SQL query
        sqlQuery = "INSERT INTO " + tb_name + " (GoogleCode, Date, Time, Open, High, Low, Close, Volume, UpdatedTime) " \
                           + "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        sqlValue = (stockQuote['symbol'], stockQuote['date'].strftime('%Y-%m-%d'), stockQuote['time'].strftime('%H:%M:%S'),
                    stockQuote['open_'], stockQuote['high'], stockQuote['low'], stockQuote['close'], stockQuote['volume'],
                    datetime.datetime.now().time().strftime("%H:%M:%S"))

        # Fire Sql Query
        cursor = conn.cursor()
        cursor.execute(sqlQuery, sqlValue)
        # Close SQL connection
        conn.commit()
        cursor.close()
        conn.close()

        # Mark DB Quote update for this stock
        currTimeQuoteDBUpdateList = currTimeQuoteDBUpdateMap.get(stockQuote['symbol'])
        currTimeQuoteDBUpdateList.append(currTime)

    '''
    Process the intraday Quotes obtained
    '''
    def processQuotes(self, stockQuoteList, quoteType, currTime):
        if len(stockQuoteList) == 0:
            # No added Quotes
            return

        if quoteType == openQuote:
            # Opening Price Quote
            stockQuote = self.prepareStockQuoteFromSelfData(0)

            # Check the time, should be within first 5min
            tickTime = stockQuote['time'].strftime('%H:%M:%S')
            tickHr = int(tickTime[0:2])
            tickMin = int(tickTime[3:5])
            if tickHr == 9 and tickMin > 14 and tickMin < 20:
                # Update Open price if its not already updated
                if stockQuote['symbol'] not in openingPriceUpdatedStocksList:
                    openingPriceUpdatedStocksList.append(stockQuote['symbol'])
                    # print("OpenQuote => ", stockQuote, file=sys.stderr)      # DEBUGGING
                    self.updateDB(stockQuote, currTime)
        elif quoteType == periodicQuote:
            # Periodic price Update
            stock = self.symbol
            # Get the time updated list of this stock
            timeUpdateList = periodicPriceUpdateDict.get(stock)
            # Go through all the data
            for tick in xrange(len(stockQuoteList)):
                tickTime = self.time[tick].strftime('%H:%M:%S')
                tickHr = int(tickTime[0:2])
                tickMin = int(tickTime[3:5])
                if tick == 0:
                    # First Quote
                    # update First Quote if Opening Quote is not updated
                    if stock not in openingPriceUpdatedStocksList and tickTime not in timeUpdateList:
                        timeUpdateList.append(tickTime)
                        stockQuote = self.prepareStockQuoteFromSelfData(tick)
                        # print("PeriodicQuote 1 => ", stockQuote, file=sys.stderr)     # DEBUGGING
                        self.updateDB(stockQuote, currTime)
                    # When Opening Quote is already updated,
                    # Update First Quote from periodic update only after first 5min
                    elif tickHr == 9 and tickMin >= 20 and tickTime not in timeUpdateList:
                        timeUpdateList.append(tickTime)
                        stockQuote = self.prepareStockQuoteFromSelfData(tick)
                        # print("PeriodicQuote 2 => ", stockQuote, file=sys.stderr)     # DEBUGGING
                        self.updateDB(stockQuote, currTime)
                    # Update First quote for Special trading days, during non normal trading days
                    elif tickHr != 9 and tickTime not in timeUpdateList:
                        timeUpdateList.append(tickTime)
                        stockQuote = self.prepareStockQuoteFromSelfData(tick)
                        # print("PeriodicQuote 3 => ", stockQuote, file=sys.stderr)     # DEBUGGING
                        self.updateDB(stockQuote, currTime)
                else:
                    # All other quotes except first
                    # Do not update after 3:20 closing time
                    if tickHr == 15 and tickMin >= 20:
                        # DO NOT UPDATE, DUMMY
                        stockQuote = self.prepareStockQuoteFromSelfData(tick)
                        # print("PeriodicQuote 4 => ", stockQuote, file=sys.stderr)     # DEBUGGING
                    # Update the time and data if not present
                    elif tickTime not in timeUpdateList:
                        timeUpdateList.append(tickTime)
                        stockQuote = self.prepareStockQuoteFromSelfData(tick)
                        # print("PeriodicQuote 5 => ", stockQuote, file=sys.stderr)     # DEBUGGING
                        self.updateDB(stockQuote, currTime)

    '''
    Intraday quotes from Google.
    Specify interval seconds and number of days
    Default 60 sec interval, 10 days data
    '''
    def __init__(self, symbol, interval_seconds=60, num_days=1, quoteType=periodicQuote, currTime='NA'):
        super(GoogleIntradayQuote, self).__init__()
        # Upper case the symbol
        self.symbol = symbol.upper()
        # Prepare the URL
        url_string = "http://www.google.com/finance/getprices?q={0}".format(self.symbol)
        url_string += "&i={0}&p={1}d&f=d,o,h,l,c,v&x=NSE".format(interval_seconds, num_days)
        stockQuoteList = []
        # Read the lines from URL
        try:
            csv = urllib.urlopen(url_string).readlines()
            # Leave the first 7 lines from top containing Metadata about the quote
            for bar in xrange(7, len(csv)):
                # Check if line contains 5 comma separated words
                if csv[bar].count(',') != 5 :
                    continue
                # Get the comma separated words
                offset, close, high, low, open_, volume = csv[bar].split(',')
                if offset[0] == 'a':
                    # the first word starts with 'a', marking a new day
                    # strip 'a' to get the timestamp of the day
                    day = float(offset[1:])
                    offset = 0
                else:
                    # if not starts with 'a', its an offset from above timestamp
                    offset = float(offset)
                # Convert OHLC to floats
                open_, high, low, close = [float(x) for x in [open_, high, low, close]]
                # Calculate the timestamp of the offsets and
                # determine the date time from the calculated timestamp
                dt = datetime.datetime.fromtimestamp(day + (interval_seconds * offset))

                # Check the Date
                dateToday = datetime.date.today().strftime('%Y-%m-%d')
                obtainedDate = dt.date().strftime('%Y-%m-%d')
                if dateToday == obtainedDate:
                    # Update the stock quote list only if the quote is of today's date
                    self.append(dt, open_, high, low, close, volume)
                    stockQuoteList.append(self)
        except:
            print("ERROR: URL OPEN FAILED for GOOGLE FINANCE, URL:[", url_string, "]", file=sys.stderr)
        # Process the Quotes List, only when updated
        if len(stockQuoteList) > 0:
            self.processQuotes(stockQuoteList, quoteType, currTime)

'''
Get the stocks for VWAP strategy
'''
def getStocksForVWAP(forDate, strategyTimeTable):
    # Get the Recommended Stocks List from DB
    # Connect to the MySQL instance
    db_host = DBserverIP
    db_user = 'root'
    db_pass = ''
    db_name = 'StocksDB'   # Remove '_' for execution, accidently DB write proof :)

    vwapStocksList = []
    # Connect to DB
    conn = mdb.connect(host=db_host, user=db_user, passwd=db_pass, db=db_name)
    try:
        # prepare SQL query
        sqlQuery = "SELECT GoogleCode,Rank FROM VWAPDateWiseRecoStocksTable WHERE TimeIntervalDBTable='" + \
                   strategyTimeTable + "' AND Date='" + forDate + "'"
        # Fire Sql Query
        cursor = conn.cursor()
        cursor.execute(sqlQuery)
        # Get results
        results = cursor.fetchall()
        for row in results:
            # Update result from Query
            stockDict = {}
            stockDict['Stock'] = row[0]
            stockDict['Rank'] = row[1]
            vwapStocksList.append(stockDict)
        # Close SQL connection
        #conn.commit()      # SELECT STATEMENT
    except:
        print("ERROR: DB SELECT FAILED for SQL Query: ", sqlQuery, file=sys.stderr)
    cursor.close()
    conn.close()
    # Sort it
    vwapStocksList = sorted(vwapStocksList, key=lambda k: k['Rank'])
    return vwapStocksList

'''
Get previous n Intraday trading days
'''
def getPreviousNTradingDays():
    # Connect to the MySQL instance
    db_host = DBserverIP
    db_user = 'root'
    db_pass = ''
    db_name = 'StocksDB'   # Remove '_' for execution, accidently DB write proof :)

    dateToday = datetime.date.today().strftime('%Y-%m-%d')
    prevDatesList = []
    # Connect to DB
    conn = mdb.connect(host=db_host, user=db_user, passwd=db_pass, db=db_name)
    try:
        # prepare SQL query
        sqlQuery = "SELECT Date FROM IntradayTradingDaysTable ORDER BY DayIndxId DESC LIMIT " + prevNumOfTradingDays
        # Fire Sql Query
        cursor = conn.cursor()
        cursor.execute(sqlQuery)
        # Get results
        results = cursor.fetchall()
        for row in results:
            # Update result from Query
            prevDatesList.append(row[0])
        # Close SQL connection
        #conn.commit()      # SELECT STATEMENT
    except:
        print("ERROR: DB SELECT FAILED for SQL Query: ", sqlQuery, file=sys.stderr)
    cursor.close()
    conn.close()
    # Reverse the list (prev days followed by latest days)
    prevDatesList.reverse()

    print("Previous Days: ", prevDatesList, file=sys.stderr)
    return prevDatesList

'''
Update previous Days Data for continuing VWAP strategy
'''
def updatePreviousData(stockList):
    # Get Previous n Days List
    prevDatesList = getPreviousNTradingDays()
    if len(prevDatesList) == 0:
        # No previous trading dates found
        return False

    # Exception marker
    isExcptnOccured = False

    # Connect to the MySQL instance
    db_host = DBserverIP
    db_user = 'root'
    db_pass = ''
    db_name = 'StocksDB'   # Remove '_' for execution, accidently DB write proof :)
    # Connect to DB
    conn = mdb.connect(host=db_host, user=db_user, passwd=db_pass, db=db_name)
    try:
        cursor = conn.cursor()
        # SQL query: Truncate existing data in vwap table
        sqlQuery = "TRUNCATE " + vwap_tb_name
        cursor.execute(sqlQuery)
        conn.commit()
    except:
        isExcptnOccured = True
        print("ERROR: DB TRUNCATE FAILED for SQL Query: ", sqlQuery, file=sys.stderr)
    cursor.close()
    conn.close()
    if isExcptnOccured == True:
        # Exception occured in Truncate SQL
        return False

    for stock in stockList:
        for tradeDate in prevDatesList:
            # Connect to the MySQL instance
            db_host = DBserverIP
            db_user = 'root'
            db_pass = ''
            db_name = 'StocksDB'   # Remove '_' for execution, accidently DB write proof :)
            # Connect to DB
            conn = mdb.connect(host=db_host, user=db_user, passwd=db_pass, db=db_name)
            try:
                cursor = conn.cursor()
                # SQL query: Get Data from IntradayFifteenMinTable for previous Days
                sqlQuery = "INSERT INTO " + vwap_tb_name
                sqlQuery += " (GoogleCode, Date, Time, Open, High, Low, Close, Volume)"
                sqlQuery += " SELECT GoogleCode, Date, Time, Open, High, Low, Close, Volume"
                sqlQuery += " FROM " + vwap_strategy_time_tb_name + " WHERE GoogleCode='" + stock + "' AND Date='" + tradeDate + "'"
                cursor.execute(sqlQuery)
                conn.commit()
            except:
                isExcptnOccured = True
                print("ERROR: DB INSERT FAILED for SQL Query: ", sqlQuery, file=sys.stderr)
            # Close SQL connection
            cursor.close()
            conn.close()
            if isExcptnOccured == True:
                # Exception occured in SQL INSERT of previous data
                return False
    # Previous Days Data Updation Succeeded
    return True

'''
Update First Quote price of each stock
'''
def updateTodaysOpenPrice(stockList, currTime):
    print("Updating Today's open price", file=sys.stderr)
    for stock in stockList:
        currTimeQuoteDBUpdateList = currTimeQuoteDBUpdateMap.get(stock.upper())
        if currTime not in currTimeQuoteDBUpdateList:
            # For Each interval get Data and Update
            q = GoogleIntradayQuote(stock, 60, 1, openQuote, currTime)
            # sleep(1)

'''
Update All other Quote prices of each stock
'''
def updateTodaysPeriodicPrice(stockList, currTime):
    print("Updating periodic price", file=sys.stderr)
    for stock in stockList:
        currTimeQuoteDBUpdateList = currTimeQuoteDBUpdateMap.get(stock.upper())
        if currTime not in currTimeQuoteDBUpdateList:
            # For Each interval get Data and Update
            q = GoogleIntradayQuote(stock, time_interval, 1, periodicQuote, currTime)
            # sleep(1)

'''
Prepare to dictionary from a given call
'''
def getCallAddDict(scripName, triggerType, triggerPrice, targetPrice):
    #form Dict
    dictData = {}
    dictData['scrip'] = scripName
    dictData['trigger'] = triggerType
    dictData['price'] = triggerPrice
    dictData['target'] = targetPrice
    return dictData

'''
send Multi call add JSON data to HTTP method
'''
def sendHTTPMultiCall(multiCallJSON):
    #post to HTTP
    post_response = requests.post(url='http://'+ HTTPServerIp +':8080/vwap/fivemin/multicalladded/', data=multiCallJSON)
    print('Call Add HTTP Response: ', post_response, file=sys.stderr)

'''
Create RServe Conn
'''
def createRServeConn():
    global Rconn
    global RconnStatus
    Rconn = pyRserve.connect(host=RServeIP, port=6311)
    Rconn.voidEval('library("quantmod")')
    Rconn.voidEval('library("PerformanceAnalytics")')
    Rconn.voidEval('library("RMySQL")')
    Rconn.voidEval('library("xts")')
    RconnStatus = True

'''
Close RServe Conn
'''
def closeRServeConn():
    global RconnStatus
    Rconn.close()
    RconnStatus = False

'''
Decide if R code require to be executed
'''
def checkForRExec(currTime):
    for stock in stockList:
        currTimeRExecList = currTimeRExecMap.get(stock)
        if currTime not in currTimeRExecList:
            return True

'''
Execute R Script to get Trade Signal from VWAP
'''
def executeRscriptTradeSignal(currTime):
    jsonDataList = []
    # Check If R code to be executed or not
    if checkForRExec(currTime) == True:
        Rconn.voidEval(RSCRIPT_VWAP_FIVEMIN_TRADE_SIGNAL)
    # Get Stock specific VWAP trade call
    for stock in stockList:
        currTimeQuoteDBUpdateList = currTimeQuoteDBUpdateMap.get(stock.upper())
        currTimeRExecList = currTimeRExecMap.get(stock)
        # Fetch VWAP call from R only if DB update happened in currTime,
        # But R code VWAP call did not execute for this stock
        if currTime in currTimeQuoteDBUpdateList and currTime not in currTimeRExecList:
            Rconn.voidEval('signal <- TradeFiveMinList[["' + stock + '"]]')
            Rconn.voidEval('currPrice <- ClosePriceList[["' + stock + '"]]')
            if Rconn.r.signal == 1:
                jsonData = getCallAddDict(stock, 'BUY', str(Rconn.r.currPrice), '0')
                jsonDataList.append(jsonData)
            elif Rconn.r.signal == -1:
                jsonData = getCallAddDict(stock, 'SELL', str(Rconn.r.currPrice), '0')
                jsonDataList.append(jsonData)
            elif Rconn.r.signal == 0:
                jsonData = getCallAddDict(stock, 'SQROFFONLY', str(Rconn.r.currPrice), '0')
                jsonDataList.append(jsonData)
            # Mark R code execution for this stock
            currTimeRExecList.append(currTime)

    # Dont send Blank JSON in HTTP data
    if len(jsonDataList) > 0:
        # Prepare JSON for the stock
        multiCallJsonArr = json.dumps(jsonDataList)
        multiCallJSON = '{"callAdded":' + multiCallJsonArr + '}'
        # Post the HTTP call
        try:
            sendHTTPMultiCall(multiCallJSON)
        except:
            print("ERROR: FAILED TO POST VWAP 5 MIN MULTI CALL", file=sys.stderr)
        # Print the call
        print(datetime.datetime.now().time().strftime("%H:%M:%S"), ": [VWAP CALL]: <", multiCallJSON, ">", file=sys.stderr)

'''
Thread Function for VWAP strategy
'''
def threadVWAPFunc():
    var = 1
    while var == 1:
        # Infinite loop of VWAP thread
        # Get Current Time
        timeNow = datetime.datetime.now().time().strftime("%H:%M:%S")
        tickHr = timeNow[0:2]
        tickMin = timeNow[3:5]
        tickSec = int(timeNow[6:8])
        currTime = tickHr+':'+tickMin

        # Match and Check the time for trigger (HACK: Allow 1 sec for google to update its price: REMOVED)
        if currTime == "09:16":
            # Trigger for Opening price Update
            try:
                # Update Opening price
                updateTodaysOpenPrice(stockList, currTime)
                try:
                    # Execute R script only if it could update price in DB
                    executeRscriptTradeSignal(currTime)
                except:
                    print("Error: ERROR: in executeRscriptTradeSignal, But Continuing", file=sys.stderr)
            except:
                #exception, but continue again
                print("Error: ERROR: in updateTodaysOpenPrice, But Continuing", file=sys.stderr)
        elif currTime in periodicTimeList:
            # Trigger for Periodic price Update
            try:
                # Update periodic price
                updateTodaysPeriodicPrice(stockList, currTime)
                try:
                    # Execute R script only if it could update price in DB
                    executeRscriptTradeSignal(currTime)
                except:
                    print("Error: ERROR: in executeRscriptTradeSignal, But Continuing", file=sys.stderr)
            except:
                #exception, but continue again
                print("Error: ERROR: in updateTodaysPeriodicPrice, But Continuing", file=sys.stderr)
        elif currTime == "15:20":
            # Close the RServe Conn
            global RconnStatus
            if RconnStatus == True:
                closeRServeConn()
                print("Rserve Conn closed", file=sys.stderr)
        # Thread Sleep
        sleep(1)

'''
main function
'''
if __name__ == '__main__':
    print("START: Entering Main", file=sys.stderr)
    # Get Stocks for VWAP 5 min
    stockList = getStocksForVWAP('ALLDAYS', vwap_strategy_time_tb_name)
    stockList = [stock['Stock'] for stock in stockList]
    if len(stockList) != 0:
        # Prepare the dictionary of time Updates
        for stock in stockList:
            # Periodic Google quote price update marker for each stock
            timeUpdateList = []
            periodicPriceUpdateDict[stock] = timeUpdateList
            # Quote DB update marker for each stock
            currTimeQuoteDBUpdateList = []
            currTimeQuoteDBUpdateMap[stock.upper()] = currTimeQuoteDBUpdateList
            # R execution update marker for each stock
            currTimeRExecList = []
            currTimeRExecMap[stock] = currTimeRExecList
        # Update previous days data into VWAP temp DB
        prevDataUpdated = updatePreviousData(stockList)
        if prevDataUpdated == True:
            # Create RServe Conn
            createRServeConn()
            print("Rserve Conn created", file=sys.stderr)
            # start the thread of VWAP Functions
            thread = Thread(target = threadVWAPFunc, args = ())
            thread.start()
            thread.join()
            print("Error: ERROR: Exiting Main", file=sys.stderr)
    # createRServeConn()              # DEBUGGING
    # executeRscriptTradeSignal()     # DEBUGGING
    # closeRServeConn()               # DEBUGGING