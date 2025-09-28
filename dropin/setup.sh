#!/bin/bash
# Copyright 2000-2025, MetaQuotes Ltd.

# Wine version to install: stable or devel
WINE_VERSION="stable"

# Prepare versions
. /etc/os-release

echo OS: $NAME $VERSION_ID

echo Get full version
sudo apt install bc wget curl -y
VERSION_FULL=$(echo "$VERSION_ID * 100" | bc -l | cut -d "." -f1)

echo Choose Wine repo
sudo rm /etc/apt/sources.list.d/winehq*

sudo dpkg --add-architecture i386
sudo mkdir -pm755 /etc/apt/keyrings
sudo wget -O - https://dl.winehq.org/wine-builds/winehq.key | sudo gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key -

if [ "$NAME" = "Ubuntu" ]; then
   echo Ubuntu found: $NAME $VERSION_ID
   # Choose repository based on Ubuntu version
   if (( $VERSION_FULL >= 2410 )); then
      sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/plucky/winehq-plucky.sources
   elif (( $VERSION_FULL < 2410 )) && (( $VERSION_FULL >= 2400 )); then
      sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/noble/winehq-noble.sources
   elif (( $VERSION_FULL < 2400 )) && (( $VERSION_FULL >= 2300 )); then
      sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/lunar/winehq-lunar.sources
   elif (( $VERSION_FULL < 2300 )) && (( $VERSION_FULL >= 2210 )); then
      sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/kinetic/winehq-kinetic.sources
   elif (( $VERSION_FULL < 2210 )) && (( $VERSION_FULL >= 2100 )); then
      sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/jammy/winehq-jammy.sources
   elif (( $VERSION_FULL < 2100 )) && (($VERSION_FULL >= 2000 )); then
      sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/focal/winehq-focal.sources
   else
      sudo wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/bionic/winehq-bionic.sources
   fi

    echo Install Wine and Wine Mono
    sudo apt update
    sudo apt install --install-recommends winehq-$WINE_VERSION -y
fi

echo Set environment to Windows 11
WINEPREFIX=~/.mt5 winecfg -v=win11

echo Install WebView2 Runtime
WINEPREFIX=~/.mt5 wine webview2.exe /silent /install

echo Install MetaTrader 5
WINEPREFIX=~/.mt5 wine mt5setup.exe

sleep 30

echo install Python packages
WINEPREFIX=~/.mt5 wine python-3.9.13-amd64.exe /quiet InstallAllUsers=1 PrependPath=1 Include_doc=0

sleep 30

echo 
WINEPREFIX=~/.mt5 wine python -m pip install --upgrade pip && WINEPREFIX=~/.mt5 wine python -m pip install -r requirements.txt

sleep 30

echo Run REST API server
WINEPREFIX=~/.mt5 wine python MT5REST.py 