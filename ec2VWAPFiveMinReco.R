#hostName <- "localhost"
hostName <- "172.31.32.173"
dbName <- "StocksDB"
tbName <- "VWAPFiveMinTable"
stockPriceXtsLol <- list()
stockPriceFiveMinXtsList <- list()
TradeFiveMinList <- list()
ClosePriceList <- list()

sql_conn <- dbConnect(MySQL(), user = "root", password = "", dbname = dbName, host = hostName)
symbol_sql_command <- paste("SELECT DISTINCT GoogleCode FROM ", tbName, sep = "")
symbol_sql_result <- dbGetQuery(sql_conn, symbol_sql_command)
dbDisconnect(sql_conn)
for(i in 1:length(symbol_sql_result[,1])){
  symbol <- symbol_sql_result[i,]
  sql_conn <- dbConnect(MySQL(), user = "root", password = "", dbname = dbName, host = hostName)
  quote_sql_command <- paste("SELECT Date, Time, Open, High, Low, Close, Volume FROM ", dbName, ".",
                             tbName, " WHERE GoogleCode = '", symbol, "';", sep = "")
  quote_sql_result <- dbGetQuery(sql_conn, quote_sql_command)
  dbDisconnect(sql_conn)
  dateTime <- paste(quote_sql_result$Date, quote_sql_result$Time, sep = " ")
  timeIndx <- strptime(dateTime, format = "%Y-%m-%d %H:%M:%S")
  prices <- quote_sql_result[, c("Open", "High", "Low", "Close", "Volume")]
  stockPriceFiveMinXtsList[[symbol]] <- as.xts(prices, timeIndx)
}
stockPriceXtsLol[["IntradayFiveMinTable"]] <- stockPriceFiveMinXtsList

for(i in 1:length(stockPriceXtsLol$IntradayFiveMinTable)){
  symbol <- stockPriceXtsLol$IntradayFiveMinTable[[i]]
  symbolName <- names(stockPriceXtsLol$IntradayFiveMinTable)[i]
  nlookback <- 3
  uLim <- 1.001
  lLim <- 0.999
  time_index <- as.POSIXct(index(symbol), format = "%Y-%m-%d %H:%M:%S")
  symbol <- apply(symbol, 2, as.numeric)
  symbol <- xts(symbol, time_index)
  
  vwap <- VWAP(Cl(symbol), Vo(symbol), n=nlookback)
  clPrice <- Cl(symbol)
  intraBarRet <- Delt(Cl(symbol), k=1, type="arithmetic")
  signal <- Cl(symbol) / vwap
  signal[is.na(signal)] <- 1
  trade <- apply(signal, 1, function(x) {
    if(x < lLim) { 
      return (1) 
    } else { 
      if(x > uLim) { 
        return(-1) 
      } else { 
        return (0) 
      }
    }
  })
  TradeFiveMinList[[symbolName]] <- as.numeric(trade[length(trade)])
  ClosePriceList[[symbolName]] <- as.numeric(clPrice[length(clPrice)])
}